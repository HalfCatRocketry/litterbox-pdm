"""Tests for the Import window's Project box and for opening a saved scan that was imported from before. The window
is replaced by stand-ins (tests/support/gui_fakes.py), so these check the wiring. They need Linux, macOS or WSL."""

import types
import unittest

from litterbox.core.projects import Project
from litterbox.importing import manifest as manifest_module
from litterbox.records import record_store
from litterbox.vault import config_write
from tests.gui.windows import test_import_window as window_tests
from tests.support.vault_fixture import SKIP_ON_WINDOWS, git


@SKIP_ON_WINDOWS
class ProjectsAndSavedScans(window_tests.ImportWindowHarness, unittest.TestCase):
    def add_project(self):
        with self.user("Alex"):
            config_write.set_values(self.a, projects=[Project("Rover", "12")])
            git(self.a, "commit", "-am", "Add project Rover")
            git(self.a, "push")

    def choose(self, label):
        with self.user("Alex"):
            self.window.project_var.set(label)
            self.window._project_chosen(label)
            self.pump_until_idle()

    def test_with_no_projects_the_box_is_hidden(self):
        self.scan()
        self.assertEqual(self.window.project_choices, {"No project": None})

    def test_choosing_a_project_numbers_the_rows_in_its_block_and_the_parts_join_it(self):
        self.add_project()
        self.scan()
        self.assertIn("Rover (12000 to 12999)", self.window.project_choices)
        self.choose("Rover (12000 to 12999)")
        self.assertTrue(all(r["values"][1].startswith("HCR-12") for r in self.rows()))
        self.assertIn("Importing into project Rover", self.window.status.options["text"])
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        pns = self.imported[0].pns
        self.assertEqual({record_store.load(self.a, pn).project for pn in pns}, {"Rover"})

    def test_a_same_base_number_outside_the_project_is_dropped_when_it_is_chosen(self):
        self.add_project()
        self.scan()
        self.window.family_entry = types.SimpleNamespace(get=lambda: "500", configure=lambda **k: None)
        self.window.family_var.set(True)
        with self.user("Alex"):
            self.window._family_toggled()
            self.pump_until_idle()
        self.choose("Rover (12000 to 12999)")
        self.assertFalse(self.window.family_var.get())
        self.assertIsNone(self.window.family_applied)

    def import_everything(self):
        self.make_manifest()
        with self.user("Alex"):
            self.window._start_job(dict(manifest_path=str(self.manifest_path)), "Opening")
            self.pump_until_idle()
            self.window._finish()
            self.pump_until_idle()
        self.window = self.open_window()

    def open_saved(self):
        self.gui.filedialog.askopenfilename = lambda **k: str(self.manifest_path)
        with self.user("Alex"):
            self.window._open_manifest()
            self.pump_until_idle()

    def test_a_saved_scan_already_imported_asks_and_ok_imports_it_again(self):
        self.import_everything()
        self.box.calls.clear()
        self.open_saved()
        asked = [c for c in self.box.calls if c[0] == "askokcancel"]
        self.assertEqual(len(asked), 1)
        self.assertIn("All parts found may already have been imported", asked[0][1][1])
        self.assertEqual((self.window.mode, len(self.rows())), ("table", 4))
        before = manifest_module.load(self.manifest_path)
        self.assertTrue(all(item.pn for item in before.items if item.include))     # the old scan is left as it was

    def test_a_saved_scan_already_imported_and_cancel_changes_nothing(self):
        self.import_everything()
        self.box.answer = False
        self.open_saved()
        self.assertEqual(self.window.mode, "pick")
        self.assertIn("Import cancelled", self.window.status.options["text"])


if __name__ == "__main__":
    unittest.main()
