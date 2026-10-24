"""
Tests for making open SolidWorks documents writable after a check-out (cad/solidworks/sw_reload.py, the words in
gui/logic/solidworks_text.py and the window's wiring), with a pretend SolidWorks. The real one can only be tried on
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


class Wiring(unittest.TestCase):
    """After a check-out the window asks SolidWorks, then makes what it has open writable, then warns about the rest."""

    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
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


if __name__ == "__main__":
    unittest.main()
