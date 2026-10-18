"""Tests for the main window's use of the SolidWorks watcher (gui/main_window/solidworks_watch.py). The window
itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look."""

import types
import unittest

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes

from litterbox.cad.solidworks import sw_documents
from litterbox.cad.solidworks import sw_watcher
from litterbox.cad.solidworks.sw_documents import OpenDocument
from litterbox.core.part_number import PN
from litterbox.parts.part_status import PartStatus

REPO = "C:/vault"
PRT = "cad/HCR-00001-001_A.SLDPRT"
PART = PN("HCR", 1, 1)


class FakeWatcher:
    def __init__(self, *docs):
        self.docs = {sw_documents.key(f"{REPO}/{rel}"): OpenDocument(f"{REPO}/{rel}", unsaved, False, True)
                     for rel, unsaved in docs}

    def snapshot(self):
        return dict(self.docs)


class SolidWorksWiring(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: REPO
        app.settings = {"solidworks_watch": True}
        self.said, self.logged = [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app._log = self.logged.append
        row = PartStatus(PART, "Part", "in_work", "Checked out by you", "mine", files=[PRT], revisions={"A": [PRT]})
        app.rows, app.rows_by_pn = [row], {PART: row}
        app.jobs = types.SimpleNamespace(pending_parts=lambda: {})
        self.app = app

    def asked(self):
        return [call for call in self.box.calls if call[0] == "askyesno"]

    def test_without_the_watcher_nothing_is_asked(self):
        self.assertTrue(self.app._saved_in_solidworks([PRT], "check in"))
        self.assertTrue(self.app._closed_in_solidworks([PRT]))
        self.assertIsNone(self.app._open_in_solidworks([PRT]))
        self.assertEqual(self.asked(), [])

    def test_unsaved_changes_are_asked_about_before_check_in(self):
        self.app.sw_watcher = FakeWatcher((PRT, True))
        self.box.answer = False
        self.assertFalse(self.app._saved_in_solidworks([PRT], "check in"))
        self.assertIn("not saved yet", self.asked()[0][1][1])
        self.box.answer = True
        self.assertTrue(self.app._saved_in_solidworks([PRT], "check in"))

    def test_saved_files_are_not_asked_about(self):
        self.app.sw_watcher = FakeWatcher((PRT, False))
        self.assertTrue(self.app._saved_in_solidworks([PRT], "check in"))
        self.assertEqual(self.asked(), [])

    def test_with_popups_off_it_is_only_logged(self):
        self.app.sw_watcher = FakeWatcher((PRT, True))
        self.app.settings["solidworks_popups"] = False
        self.assertTrue(self.app._saved_in_solidworks([PRT], "check in"))
        self.assertTrue(self.app._closed_in_solidworks([PRT]))
        self.assertEqual(self.asked(), [])
        self.assertEqual(len(self.logged), 2)

    def test_get_latest_asks_when_a_file_it_may_replace_is_open(self):
        self.app.sw_watcher = FakeWatcher((PRT, False))
        self.app.rows[0].kind = "ok"                                    # not yours: Get Latest may replace it
        started = []
        self.app.run_task = lambda *a, **k: started.append(a)
        self.box.answer = False
        self.app.get_latest()
        self.assertEqual(started, [])
        self.assertIn("open in SolidWorks", self.asked()[0][1][1])

    def test_your_own_checked_out_files_dont_stop_get_latest(self):
        self.app.sw_watcher = FakeWatcher((PRT, False))                 # the row is "mine"
        started = []
        self.app.run_task = lambda *a, **k: started.append(a)
        self.app.get_latest()
        self.assertEqual(len(started), 1)
        self.assertEqual(self.asked(), [])

    def test_a_part_being_checked_in_that_gets_opened_is_warned_about(self):
        self.app.jobs = types.SimpleNamespace(pending_parts=lambda: {str(PART): "Checking in 1 part"})
        changes = sw_watcher.differences({}, FakeWatcher((PRT, False)).snapshot())
        self.app._solidworks_changed(changes)
        warnings = [call for call in self.box.calls if call[0] == "showwarning"]
        self.assertIn("was opened in SolidWorks", warnings[0][1][1])

    def test_after_get_latest_only_the_open_updated_files_are_named(self):
        self.app.sw_watcher = FakeWatcher((PRT, False))
        self.app._warn_open_files([PRT, "cad/HCR-00002-001_A.SLDPRT"])
        info = [call for call in self.box.calls if call[0] == "showinfo"]
        self.assertIn("HCR-00001-001_A.SLDPRT", info[0][1][1])
        self.assertNotIn("HCR-00002-001", info[0][1][1])
        self.box.calls.clear()
        self.app.sw_watcher = FakeWatcher()                             # nothing open: nothing to say
        self.app._warn_open_files([PRT])
        self.assertEqual(self.box.calls, [])


if __name__ == "__main__":
    unittest.main()
