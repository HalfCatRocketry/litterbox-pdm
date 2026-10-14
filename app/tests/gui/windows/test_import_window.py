"""Tests for the Import window (gui/windows/import_window). The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import queue
import types
import unittest
from unittest import mock
from tests.support.import_fixture import ImportFixture
from tests.support.gui_source import gui_source
from tests.support.vault_fixture import SKIP_ON_WINDOWS
from litterbox.importing import session as import_session
from litterbox.records import record_store
from litterbox.user import settings
from litterbox.parts import create_batch
from litterbox.core import part_number
from tests.support.gui_fakes import REAL_SESSION, FakeBox, load_gui_with_fakes, FakeParent


@SKIP_ON_WINDOWS
class ImportWindowWiring(ImportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        patcher = mock.patch.object(settings, "ROOT", self.tmp / "litterbox-settings")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.imported = []
        self.window = self.open_window()

    def open_window(self, cots=False):
        with mock.patch.object(import_session, "ImportSession", lambda *a, **k: self.make_session(*a, **k)):
            return self.gui.import_window.ImportWindow(FakeParent(), str(self.a), "HCR", self.imported.append, cots=cots)

    def make_session(self, repo, post, log=None, org=None):
        self.session = REAL_SESSION(repo, post, backend_factory=lambda: self.fake, log=log or (lambda t: None),
                                                    org=org, gap=0, jitter=0)
        self.addCleanup(lambda: (self.session.close(), self.session._thread.join(5)))
        return self.session

    def pump_until_idle(self):
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                work = self.window.inbox.get(timeout=0.2)
            except queue.Empty:
                if not self.window.running:
                    return
                continue
            work()
            if not self.window.running:
                return
        self.fail("the background job never finished")

    def scan(self):
        self.window.folders.append(str(self.src))
        with self.user("Alex"):
            self.window._scan()
            self.assertTrue(self.window.running)
            self.pump_until_idle()

    def rows(self):
        return list(self.window.tree.rows.values())

    # -- tests -------------------------------------------------------------------
    def test_scanning_fills_the_table(self):
        self.scan()
        self.assertEqual(self.window.mode, "table")
        self.assertEqual(len(self.rows()), 4)
        first = self.rows()[0]["values"]
        self.assertEqual(first[0], "☑")
        self.assertTrue(first[1].startswith("HCR-"))
        self.assertEqual(self.window.primary.options["text"], "Finish & Import")
        self.assertIn("4 of 4", self.window.summary.options["text"])

    def test_scanning_with_no_folder_says_so(self):
        self.window._scan()
        self.assertIn("Add at least one folder", self.window.status.options["text"])
        self.assertEqual(self.window.mode, "pick")

    def test_a_bad_scan_goes_back_to_the_first_page_with_a_message(self):
        self.window.folders.append(str(self.tmp / "does-not-exist"))
        self.window._scan()
        self.pump_until_idle()
        self.assertEqual(self.window.mode, "pick")
        self.assertTrue(any(c[0] == "showerror" for c in self.box.calls))

    def test_unticking_a_row_updates_the_table(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        event = types.SimpleNamespace(x=5, y=5)
        self.window.tree.identify_region = lambda x, y: "cell"
        self.window.tree.identify_column = lambda x: "#1"
        self.window.tree.identify_row = lambda y: iid
        with self.user("Alex"):
            self.window._on_click(event)
            self.pump_until_idle()
        self.assertEqual(self.window.tree.rows[iid]["values"][0], "☐")
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("off",))
        self.assertIn("3 of 4", self.window.summary.options["text"])

    def click(self, iid, shift=False):
        tree = self.window.tree
        tree.identify_region = lambda x, y: "cell"
        tree.identify_column = lambda x: "#1"
        tree.identify_row = lambda y: iid
        with self.user("Alex"):
            self.window._on_click(types.SimpleNamespace(x=5, y=5, state=1 if shift else 0))
            self.pump_until_idle()

    def marks(self):
        return [r["values"][0] for r in self.rows()]

    def test_shift_click_selects_or_deselects_everything_between(self):
        self.scan()
        ids = list(self.window.tree.rows)
        self.click(ids[0])                                    # deselect the first
        self.click(ids[2], shift=True)                        # and everything down to the third
        self.assertEqual(self.marks(), ["☐", "☐", "☐", "☑"])
        self.click(ids[3])                                    # deselect the last
        self.click(ids[0])                                    # select the first again
        self.click(ids[2], shift=True)                        # and everything down to the third
        self.assertEqual(self.marks(), ["☑", "☑", "☑", "☐"])

    def test_select_all_and_deselect_all_buttons(self):
        self.scan()
        with self.user("Alex"):
            self.window._tick_all(False)
            self.pump_until_idle()
            self.assertEqual(self.marks(), ["☐"] * 4)
            self.window._tick_all(True)
            self.pump_until_idle()
        self.assertEqual(self.marks(), ["☑"] * 4)

    def use_family(self, text):
        self.window.family_entry = types.SimpleNamespace(get=lambda: text, configure=lambda **k: None)
        self.window.family_var.set(True)
        with self.user("Alex"):
            self.window._family_toggled()
            self.pump_until_idle()

    def test_same_base_number_box_gives_every_row_a_variant_of_it(self):
        self.scan()
        self.use_family("500")
        self.assertEqual([r["values"][1] for r in self.rows()],
                         [f"HCR-00500-00{n}" for n in (1, 2, 3, 4)])
        self.assertEqual(self.window.family_applied, "500")

    def test_leaving_the_box_empty_uses_the_suggested_number(self):
        self.scan()
        self.window.family_placeholder = "00777"
        self.use_family("")
        self.assertTrue(self.rows()[0]["values"][1].startswith("HCR-00777-"))

    def test_a_base_with_too_few_variants_is_refused_with_a_warning(self):
        self.scan()
        before = [r["values"][1] for r in self.rows()]
        with mock.patch.object(part_number, "MAX_VARIANT", 3), \
                mock.patch.object(create_batch, "sync_latest", lambda repo: None):      # a sync resets the digit limits
            self.use_family("500")
        self.assertEqual([r["values"][1] for r in self.rows()], before)
        self.assertFalse(self.window.family_var.get())
        self.assertTrue(any(c[0] == "showwarning" and "unused variant" in c[1][1] for c in self.box.calls))

    def test_unticking_the_box_goes_back_to_separate_numbers(self):
        self.scan()
        self.use_family("500")
        self.window.family_var.set(False)
        with self.user("Alex"):
            self.window._family_toggled()
            self.pump_until_idle()
        bases = {r["values"][1].split("-")[1] for r in self.rows()}
        self.assertEqual(len(bases), 4)
        self.assertIsNone(self.window.family_applied)

    def test_editing_a_cell(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        editor = mock.MagicMock()
        editor.get.return_value = "Edited name"
        self.window.editor = (editor, iid, "name")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["values"][2], "Edited name")
        editor.get.return_value = ("banana", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertIn("exactly 5 digits", self.window.status.options["text"])
        self.assertEqual(self.window.status.options["text_color"], self.gui.theme.WARN)

    def test_finish_imports_closes_and_tells_the_main_window(self):
        self.scan()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.assertEqual(len(self.imported[0].pns), 4)
        self.assertTrue(self.window.closed)
        self.assertTrue(any(c[0] == "showinfo" and "Imported 4 parts" in c[1][1] for c in self.box.calls))

    def test_a_taken_typed_number_keeps_the_window_open_with_red_rows(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        editor = mock.MagicMock()
        editor.get.return_value = ("00001", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(self.window.closed)
        self.assertEqual(self.window.mode, "table")
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("conflict",))
        self.assertTrue(any(c[0] == "showwarning" and "Front upright" in c[1][1] for c in self.box.calls))
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()
        # fix the red row and finish again
        editor.get.return_value = ("00900", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("typed",))
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.assertIn(part_number.PN("HCR", 900, 1), self.imported[0].pns)

    def test_cancel_button_during_the_import_returns_to_the_table_with_nothing_added(self):
        self.scan()
        real_copy = self.fake.copy
        calls = {"n": 0}

        def copy(src, dst):
            real_copy(src, dst)
            calls["n"] += 1
            if calls["n"] == 2:
                self.window._cancel_job()          # the user presses Cancel import
        self.fake.copy = copy
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(self.window.closed)
        self.assertEqual(self.window.mode, "table")
        self.assertIn("cancelled", self.window.status.options["text"].lower())
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()

    def test_closing_the_window_during_an_import_cancels_it_and_cleans_up(self):
        self.scan()
        real_copy = self.fake.copy
        calls = {"n": 0}

        def copy(src, dst):
            real_copy(src, dst)
            calls["n"] += 1
            if calls["n"] == 2:
                self.window._close()               # the user closes the window and confirms
        self.fake.copy = copy
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
            while not self.window.closed:
                self.window.inbox.get(timeout=5)()
        self.assertTrue(self.window.closed)
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()

    def test_leaving_the_number_boxes_unchanged_keeps_the_row_automatic(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        base, variant = self.window._pn_parts(iid)
        self.assertEqual((len(base), len(variant)), (5, 3))
        editor = mock.MagicMock()
        editor.get.return_value = (base, variant)
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("ok",))

    def test_outside_references_ask_the_user_instead_of_failing(self):
        self.scan()
        iid = next(i for i, r in self.window.tree.rows.items() if r["values"][2] == "p1")
        with self.user("Alex"):
            self.window._details[iid].ticked and self.window._run_quick(
                lambda done: self.session.include(int(iid), False, done))
            self.pump_until_idle()
            self.box.calls.clear()
            self.window._finish()
            self.pump_until_idle()                       # asks (the fake answers Yes), then imports
        asked = [c for c in self.box.calls if c[0] == "askyesno"]
        self.assertEqual(len(asked), 1)
        self.assertIn("not being imported", asked[0][1][1])
        self.assertEqual(len(self.imported), 1)
        self.assertEqual(len(self.imported[0].pns), 3)

    def test_saying_no_to_outside_references_imports_nothing(self):
        self.scan()
        iid = next(i for i, r in self.window.tree.rows.items() if r["values"][2] == "p1")
        self.box.answer = False
        with self.user("Alex"):
            self.window._run_quick(lambda done: self.session.include(int(iid), False, done))
            self.pump_until_idle()
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(self.imported, [])
        self.assertFalse(self.window.closed)
        self.assertIn("Nothing was imported", self.window.status.options["text"])
        self.assert_nothing_left()

    # -- Import COTS ----------------------------------------------------------------
    def make_bought_folder(self):
        """A second folder: a copy of p1 (already in the vault after the first import), a part with the
        same name as p3 but different contents, and two identical new parts."""
        bought = self.tmp / "bought"
        bought.mkdir()
        (bought / "bracket_copy.SLDPRT").write_bytes((self.src / "parts" / "p1.SLDPRT").read_bytes())
        (bought / "p3.SLDPRT").write_text("a different p3\n")
        (bought / "91251A540_bolt.SLDPRT").write_text("bolt\n")
        (bought / "bolt_again.SLDPRT").write_text("bolt\n")
        return bought

    def import_everything_first(self):
        with self.user("Alex"):
            self.scan()
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.imported.clear()

    def test_import_cots_needs_the_confirmation_box_before_it_scans(self):
        window = self.open_window(cots=True)
        self.window = window
        self.assertEqual(window.heading, "Import COTS")
        window.folders.append(str(self.src))
        window._scan()
        self.assertEqual(window.mode, "pick")
        self.assertIn("Tick the box", window.status.options["text"])
        window.cots_var.set(True)
        with self.user("Alex"):
            window._scan()
            self.pump_until_idle()
            self.pump_until_idle()
        self.assertEqual(window.mode, "table")

    def test_import_cots_warns_about_duplicates_and_asks_before_importing(self):
        self.import_everything_first()
        bought = self.make_bought_folder()
        window = self.window = self.open_window(cots=True)
        window.cots_var.set(True)
        window.folders.append(str(bought))
        with self.user("Alex"):
            window._scan()
            self.pump_until_idle()               # the scan
            self.pump_until_idle()               # the duplicate check that follows it
            by_name = {r["values"][2]: r for r in window.tree.rows.values()}
            self.assertEqual(by_name["bracket copy"]["tags"], ("warn",))      # same contents as a part in the vault
            self.assertEqual(by_name["p3"]["tags"], ("warn",))                # same name as a part in the vault
            self.assertEqual(by_name["91251A540 bolt"]["tags"], ("warn",))    # identical to another row of this import
            self.box.calls.clear()
            self.box.answer = False                                           # the user says No
            window._finish()
            self.pump_until_idle()
        question = next(c for c in self.box.calls if c[0] == "askyesno")
        self.assertIn("record every one as COTS", question[1][1])
        self.assertIn("identical to the one in the vault", question[1][1])
        self.assertIn("exactly this name", question[1][1])
        self.assertEqual(self.imported, [])
        self.assertIn("Nothing was imported", window.status.options["text"])
        self.assertEqual(len(list((self.a / "PN-logs").iterdir())), 5)         # only the first import's records
        self.box.answer = True                                                 # the user says Yes
        with self.user("Alex"):
            window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        records = [record_store.load(self.a, pn) for pn in self.imported[0].pns]
        self.assertEqual(len(records), 4)
        self.assertTrue(all(r.cots and r.imported for r in records))

    def test_a_normal_import_never_asks_the_cots_question_or_marks_cots(self):
        self.scan()
        self.box.calls.clear()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(any(c[0] == "askyesno" for c in self.box.calls))
        self.assertTrue(all(not record_store.load(self.a, pn).cots for pn in self.imported[0].pns))

    def test_refresh_numbers_reports_the_result(self):
        self.scan()
        with self.user("Alex"):
            self.window._refresh_numbers()
            self.pump_until_idle()
        self.assertIn("available", self.window.status.options["text"])

    def test_the_main_window_has_an_import_button(self):
        source = gui_source()
        self.assertIn('("Import...", self.import_cad', source)


if __name__ == "__main__":
    unittest.main()
