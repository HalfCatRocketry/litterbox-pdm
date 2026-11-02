"""
Tests for making open SolidWorks documents writable after a check-out, and Refresh Read State
(cad/solidworks/sw_reload.py, the words in gui/logic/solidworks_text.py and the window's wiring), with a pretend
SolidWorks. The real one can only be tried on
Windows with SolidWorks installed.
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from litterbox.cad.solidworks import sw_documents
from litterbox.cad.solidworks import sw_reload
from litterbox.gui.logic import solidworks_text
from tests.cad.solidworks.test_sw_watcher import FakeDoc, FakeSolidWorks, doc
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace

REPO = os.path.abspath("hcr")                      # paths as this system writes them, so the tests run anywhere
PRT, DRW, ASM = (os.path.join(REPO, "cad", name) for name in
                 ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW", "HCR-00002-001_A.SLDASM"))


class WritableDoc(FakeDoc):
    """A document whose read-only state can be changed, as ModelDoc2's can (or that refuses, like a busy one)."""

    def __init__(self, path, refuse=False, **kw):
        super().__init__(path, **kw)
        self.refuse, self.calls = refuse, []

    def SetReadOnlyState(self, read_only):
        self.calls.append(("set", read_only))
        if self.refuse:
            raise RuntimeError("busy")
        self.read_only = read_only

    def ReloadOrReplace(self, read_only, replace_with, dont_save):
        self.calls.append(("reload", read_only, replace_with, dont_save))
        self.read_only, self.unsaved = read_only, False


class Reload(unittest.TestCase):
    def solidworks(self, *docs):
        sw = FakeSolidWorks(*docs)
        patcher = mock.patch.object(sw_documents, "attach", lambda: sw)
        patcher.start()
        self.addCleanup(patcher.stop)
        return sw

    def test_only_the_read_only_ones_among_these_are_found(self):
        self.solidworks(WritableDoc(PRT, read_only=True), WritableDoc(DRW), WritableDoc(ASM, read_only=True))
        found = sw_reload.open_read_only([PRT, DRW, PRT.lower()])
        self.assertEqual([d.path for d in found], [PRT])
        with mock.patch.object(sw_documents, "attach", lambda: None):
            self.assertIsNone(sw_reload.open_read_only([PRT]))          # SolidWorks isn't running

    def test_switched_in_place_or_reloaded_then_read_back(self):
        part, drawing = WritableDoc(PRT, read_only=True, unsaved=True), WritableDoc(DRW, read_only=True)
        self.solidworks(part, drawing)
        done, failed = sw_reload.make_writable([PRT, DRW], reload=[DRW])
        self.assertEqual((done, failed), ([PRT, DRW], []))
        self.assertEqual(part.calls, [("set", False)])                  # unsaved changes kept
        self.assertEqual(drawing.calls, [("reload", False, "", True)])

    def test_a_refusal_or_a_closed_document_is_reported_never_raised(self):
        self.solidworks(WritableDoc(PRT, read_only=True, refuse=True))
        done, failed = sw_reload.make_writable([PRT, ASM])
        self.assertEqual(done, [])
        self.assertIn("busy", dict(failed)[PRT])
        self.assertIn("isn't open", dict(failed)[ASM])
        with mock.patch.object(sw_documents, "attach", lambda: None):
            self.assertEqual(sw_reload.make_writable([PRT])[1], [(PRT, "SolidWorks isn't running")])

    def test_everything_open_is_found_and_made_read_only_keeping_unsaved_changes(self):
        part = WritableDoc(PRT, unsaved=True)
        self.solidworks(part, WritableDoc(DRW, read_only=True))
        self.assertEqual([d.path for d in sw_reload.open_all()], [PRT, DRW])
        self.assertEqual(sw_reload.make_read_only([PRT]), ([PRT], []))
        self.assertEqual(part.calls, [("set", True)])
        self.assertTrue(part.unsaved)
        with mock.patch.object(sw_documents, "attach", lambda: None):
            self.assertIsNone(sw_reload.open_all())

    def test_a_document_that_stays_writable_is_reported(self):
        class Stubborn(WritableDoc):
            def SetReadOnlyState(self, read_only):
                self.calls.append(("set", read_only))
        self.solidworks(Stubborn(PRT))
        self.assertEqual(sw_reload.make_read_only([PRT]), ([], [(PRT, "SolidWorks kept it writable")]))


class ComObjects(unittest.TestCase):
    def test_a_property_that_gives_a_com_object_is_not_called(self):
        """Through COM, sw.GetFirstDocument gives the document, which Python counts as callable; calling it asks for
        its default member, which SolidWorks hasn't ("Member not found"). Seen with SolidWorks 2024."""
        from litterbox.cad.solidworks import com

        class ComObject:
            _oleobj_ = object()

            def __call__(self):
                raise RuntimeError("Member not found.")

        document = ComObject()
        sw = SimpleNamespace(GetFirstDocument=document, GetPathName=lambda: PRT)
        self.assertIs(com.call(sw, "GetFirstDocument"), document)
        self.assertEqual(com.call(sw, "GetPathName"), PRT)                  # a method is still called


class Words(unittest.TestCase):
    def test_what_is_switched_what_is_reloaded_and_what_needs_asking(self):
        repo = REPO
        found = [doc(PRT, read_only=True), doc(DRW, read_only=True, unsaved=True), doc(ASM, read_only=True)]
        switch, reload, ask = solidworks_text.writable_plan(found, repo, ["cad/HCR-00001-001_A.SLDDRW"])
        self.assertEqual((switch, reload, ask), ([PRT, ASM], [DRW], [DRW]))
        self.assertIn("HCR-00001-001_A.SLDDRW", solidworks_text.reload_unsaved_question(ask))
        self.assertEqual(solidworks_text.writable_done_text([PRT]), "HCR-00001-001_A.SLDPRT is now writable in SolidWorks")
        self.assertIn("File > Reload", solidworks_text.writable_failed_text([(PRT, "busy")]))
        self.assertEqual(solidworks_text.still_old(repo, ["cad/HCR-00001-001_A.SLDDRW", "cad/x_A.SLDPRT"], [DRW]),
                         ["cad/x_A.SLDPRT"])

    def test_refresh_matches_each_open_vault_file_to_its_file_on_disk(self):
        key = sw_reload.open_documents.key
        elsewhere = os.path.abspath(os.path.join("other", "x.SLDPRT"))
        self.assertTrue(solidworks_text.in_vault(REPO, PRT))
        self.assertFalse(solidworks_text.in_vault(REPO, elsewhere))
        self.assertFalse(solidworks_text.in_vault(REPO, REPO + "-old/cad/a.SLDPRT"))
        found = [doc(PRT, read_only=True), doc(DRW, read_only=True, unsaved=True), doc(ASM, unsaved=True),
                 doc(elsewhere, read_only=True)]
        writable = {key(PRT): True, key(DRW): True, key(ASM): False}
        self.assertEqual(solidworks_text.read_state_plan(found, writable, {key(DRW)}),
                         ([PRT], [DRW], [DRW], [ASM]))
        self.assertEqual(solidworks_text.read_state_plan(found, {key(PRT): False, key(ASM): True}, set()),
                         ([], [], [], []))                              # already right, or not on disk
        self.assertIn("Save As", solidworks_text.read_only_done_text([ASM], [ASM]))
        self.assertIn("Read-only ticked", solidworks_text.read_only_failed_text([(ASM, "busy")]))


class Wiring(unittest.TestCase):
    """After a check-out the window asks SolidWorks, then makes what it has open writable, then warns about the rest."""

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        from litterbox.core.part_number import PN
        from litterbox.parts.part_status import PartStatus
        self.pn = PN("HCR", 1, 1)
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {self.pn: PartStatus(self.pn, "Bracket", "in_work", "Checked out by you", "mine",
                                              revisions={"A": ["cad/HCR-00001-001_A.SLDPRT",
                                                               "cad/HCR-00001-001_A.SLDDRW"]})}
        app.repo = lambda: REPO
        app.note, self.said, self.warned, self.made = "Checked out 1 part", [], [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app._log = lambda text: None
        app._warn_open_files = lambda rels: self.warned.append(rels)
        app.run_task = lambda work, done, on_success=None, **kw: on_success(work())
        self.app = app
        replace(self, sw_reload, "open_read_only",
                lambda paths: [doc(path, read_only=True) for path in paths if path.endswith("SLDPRT")])
        replace(self, sw_reload, "make_writable",
                lambda paths, reload=(): self.made.append((list(paths), list(reload))) or (list(paths), []))

    def test_open_files_become_writable_and_the_rest_are_warned_about(self):
        result = SimpleNamespace(changed_upstream=["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00005-001_A.SLDPRT"])
        self.app._after_checkout([(self.pn, result)])
        self.assertEqual(self.made, [([PRT], [PRT])])                   # newer on disk: reloaded
        self.assertIn("HCR-00001-001_A.SLDPRT is now writable in SolidWorks", self.said[-1])
        self.assertEqual(self.warned, [["cad/HCR-00005-001_A.SLDPRT"]])  # not open here: the usual note

    def test_solidworks_not_running_leaves_just_the_usual_note(self):
        replace(self, sw_reload, "open_read_only", lambda paths: None)
        self.app._after_checkout([(self.pn, SimpleNamespace(changed_upstream=[]))])
        self.assertEqual((self.made, self.warned), ([], [[]]))


class RefreshWiring(unittest.TestCase):
    """Refresh Read State: SolidWorks' open vault files are made to match their files on disk."""

    def setUp(self):
        Wiring.setUp(self)
        self.locked = []
        replace(self, sw_reload, "make_read_only",
                lambda paths: self.locked.append(list(paths)) or (list(paths), []))
        self.disk = {}
        real_access, real_isfile = os.access, os.path.isfile
        replace(self, os, "access", lambda path, mode: self.disk.get(path, real_access(path, mode)))
        replace(self, os.path, "isfile", lambda path: path in self.disk or real_isfile(path))

    def open_now(self, *docs):
        replace(self, sw_reload, "open_all", lambda: list(docs))

    def test_a_writable_file_open_read_only_becomes_writable_and_a_read_only_one_read_only(self):
        self.disk = {PRT: True, DRW: False}
        self.open_now(doc(PRT, read_only=True), doc(DRW, unsaved=True))
        self.app.refresh_read_state()
        self.assertEqual((self.made, self.locked), ([([PRT], [])], [[DRW]]))
        self.assertIn("HCR-00001-001_A.SLDPRT is now writable", self.said[-1])
        self.assertIn("HCR-00001-001_A.SLDDRW is now read-only", self.said[-1])

    def test_a_file_check_out_left_stale_is_reloaded_not_switched(self):
        self.disk = {PRT: True}
        self.open_now(doc(PRT, read_only=True, unsaved=True))
        self.box.answer = False                          # No: keep the unsaved changes
        self.app._mark_stale([PRT], [])
        self.app.refresh_read_state()
        self.assertEqual(self.made, [])                                 # never made writable over the newer file
        self.box.answer = True
        self.app.refresh_read_state()
        self.assertEqual(self.made, [([PRT], [PRT])])
        self.assertEqual(self.app.stale_in_cad, set())

    def test_nothing_to_do_or_solidworks_not_running_says_so(self):
        self.disk = {PRT: False}
        self.open_now(doc(PRT, read_only=True))
        self.app.refresh_read_state()
        self.assertIn("already", self.said[-1])
        replace(self, sw_reload, "open_all", lambda: None)
        self.app.refresh_read_state()
        self.assertEqual(self.said[-1], "SolidWorks isn't running")
        self.assertEqual((self.made, self.locked), ([], []))

    def test_it_is_in_the_part_menu_below_open_pdf(self):
        menu = self.gui.menus.PART_MENU
        self.assertEqual(menu[menu.index(("Open PDF", "open_pdf")) + 1], ("Refresh Read State", "refresh_read_state"))


if __name__ == "__main__":
    unittest.main()
