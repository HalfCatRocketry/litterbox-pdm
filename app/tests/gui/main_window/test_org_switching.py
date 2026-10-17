"""Tests for Create new vault and the org box. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace


class CreateVaultWiring(unittest.TestCase):
    """The Create new vault... entry in the org menu."""

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
        self.dialog_result = ("HCR", "C:\\Litterbox\\hcr", 1, 5, 3, "Hidden Creek Robotics")
        self.gui.org_dialog.OrgDialog = lambda *a, **k: SimpleNamespace(show=lambda: self.dialog_result)
        self.plan = SimpleNamespace(ok=True, problems=[], warnings=[], org="HCR")
        replace(self, self.gui.create_vault, "plan", lambda *a, **k: self.plan)
        replace(self, self.gui.settings, "save", lambda data: None)

    def shown(self, name):
        return [call for call in self.box.calls if call[0] == name]

    def test_choosing_the_menu_entry_starts_it(self):
        started = []
        self.app.create_vault = lambda: started.append(True)
        self.app.on_org_chosen(self.gui.org_menu.CREATE_VAULT)
        self.assertEqual(started, [True])

    def test_not_having_cloned_it_yet_stops_at_the_first_question(self):
        self.box.answer = False
        self.app.create_vault()
        self.assertEqual(self.tasks, [])

    def test_problems_are_shown_and_nothing_runs(self):
        self.plan.ok, self.plan.problems = False, ["No remote."]
        self.app.create_vault()
        self.assertEqual(self.tasks, [])
        self.assertIn("No remote.", self.shown("showerror")[0][1][1])

    def test_a_declined_warning_stops_it(self):
        self.plan.warnings = ["Only 999 parts."]
        answers = iter([True, False])
        self.gui.messagebox.askyesno = lambda *a, **k: next(answers)
        self.app.create_vault()
        self.assertEqual(self.tasks, [])

    def test_creating_runs_in_the_background_and_then_opens_the_new_org(self):
        from types import SimpleNamespace
        calls = []
        replace(self, self.gui.create_vault, "create", lambda *a, **k: calls.extend((a, k)) or "made")
        self.app.create_vault()
        work, done, on_success = self.tasks[0]
        self.assertEqual(work(), "made")
        self.assertEqual(calls[0][:5], ("C:\\Litterbox\\hcr", "HCR", 1, 5, 3))
        self.assertEqual(calls[1]["org_name"], "Hidden Creek Robotics")
        on_success(SimpleNamespace(org="HCR", pushed=True, owner=None, team_error="", warnings=[]))
        self.assertEqual(self.switched, ["HCR"])
        self.assertEqual(self.app.settings["orgs"], {"HCR": "C:\\Litterbox\\hcr"})
        self.assertTrue(self.shown("showinfo"))


if __name__ == "__main__":
    unittest.main()
