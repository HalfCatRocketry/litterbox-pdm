"""Tests for Create new org and the org box. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace

URL = "https://dev.azure.com/team/project/_git/hcr-litterbox"


class CreateVaultWiring(unittest.TestCase):
    """The Create new org... entry in the File menu."""

    def setUp(self):
        from types import SimpleNamespace
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.tasks, self.switched = [], []
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, done, on_success))
        app.switch_org = self.switched.append
        app._reload_org_menu = lambda: None
        app.settings = {}
        self.app = app
        self.dialog_result = (URL, "HCR", 1, 5, 3, "Hidden Creek Robotics", 500)
        self.gui.org_dialog.OrgDialog = lambda *a, **k: SimpleNamespace(show=lambda: self.dialog_result)
        self.checked = SimpleNamespace(ok=True, problems=[], warnings=[], org="HCR")
        replace(self, self.gui.create_vault, "check_settings", lambda *a, **k: self.checked)
        replace(self, self.gui.settings, "save", lambda data: None)
        replace(self, self.gui.settings, "ROOT", "C:\\Litterbox")
        self.cloned = []
        replace(self, self.gui.vault_clone, "clone_or_reuse",
                lambda url, target, on_demand=True: self.cloned.append((url, target)) or target)
        self.git = ("Alex Smith", "alex@x.com")                       # what git knows, whatever this computer has
        replace(self, self.gui.git_identity, "current", lambda folder: self.git)

    def shown(self, name):
        return [call for call in self.box.calls if call[0] == name]

    def test_choosing_the_menu_entry_starts_it(self):
        started = []
        self.app.create_vault = lambda: started.append(True)
        self.app.on_org_chosen(self.gui.org_menu.CREATE_VAULT)
        self.assertEqual(started, [True])

    def test_not_having_made_the_repository_yet_stops_at_the_first_question(self):
        self.box.answer = False
        self.app.create_vault()
        self.assertEqual(self.tasks, [])

    def test_problems_are_shown_and_nothing_runs(self):
        self.checked.ok, self.checked.problems = False, ["Org code too long."]
        self.app.create_vault()
        self.assertEqual(self.tasks, [])
        self.assertIn("Org code too long.", self.shown("showerror")[0][1][1])

    def test_a_vault_that_is_already_added_is_refused(self):
        replace(self, self.gui.org_menu, "plan_add_org", lambda *a: (None, "HCR is already added"))
        self.app.create_vault()
        self.assertEqual(self.tasks, [])
        self.assertIn("HCR is already added", self.shown("showerror")[0][1][1])

    def test_it_says_the_settings_cant_be_changed_and_stops_if_you_say_no(self):
        self.checked.warnings = ["Only 999 parts."]
        questions = []
        answers = iter([True, False])
        self.gui.messagebox.askyesno = lambda title, text, **k: questions.append(text) or next(answers)
        self.app.create_vault()
        self.assertEqual(self.tasks, [])
        self.assertIn("can't change them", questions[1])
        self.assertIn("HCR-00001-001", questions[1])
        self.assertIn("Only 999 parts.", questions[1])

    def test_it_clones_then_creates_in_the_background_and_opens_the_new_org(self):
        from pathlib import Path
        from types import SimpleNamespace
        calls = []
        replace(self, self.gui.create_vault, "create", lambda *a, **k: calls.extend((a, k)) or "made")
        self.app.create_vault()
        self.assertEqual(self.cloned, [])                                  # nothing happens until the task runs
        work, done, on_success = self.tasks[0]
        folder, created = work()
        target = Path("C:\\Litterbox") / "hcr-litterbox"
        self.assertEqual(self.cloned, [(URL, target)])
        self.assertEqual((folder, created), (target, "made"))
        self.assertEqual(calls[0][:5], (target, "HCR", 1, 5, 3))
        self.assertEqual((calls[1]["org_name"], calls[1]["assembly_variant_start"]), ("Hidden Creek Robotics", 500))
        on_success((folder, SimpleNamespace(org="HCR", pushed=True, owner=None, team_error="", warnings=[])))
        self.assertEqual(self.switched, ["HCR"])
        self.assertEqual(self.app.settings["orgs"], {"HCR": str(target)})
        self.assertTrue(self.shown("showinfo"))

    def test_without_a_git_name_it_asks_first_and_sets_it_in_the_new_vault(self):
        from types import SimpleNamespace
        self.git, saved, self.answer = ("", ""), [], ("Alex Smith", "alex@x.com")
        self.gui.git_identity_dialog.GitIdentityDialog = lambda *a, **k: SimpleNamespace(show=lambda: self.answer)
        replace(self, self.gui.git_identity, "save", lambda folder, name, email: saved.append((folder, name, email)))
        replace(self, self.gui.create_vault, "create", lambda *a, **k: "made")
        self.app.create_vault()
        work, _done, _on_success = self.tasks[0]
        folder, _created = work()
        self.assertEqual(saved, [(folder, "Alex Smith", "alex@x.com")])     # after the clone, in the vault

    def test_without_a_git_name_not_now_stops(self):
        from types import SimpleNamespace
        self.git = ("", "")
        self.gui.git_identity_dialog.GitIdentityDialog = lambda *a, **k: SimpleNamespace(show=lambda: None)
        self.app.create_vault()
        self.assertEqual(self.tasks, [])


if __name__ == "__main__":
    unittest.main()
