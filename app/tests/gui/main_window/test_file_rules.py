"""Tests for gui/main_window/file_rules.py: after a refresh, an outdated vault's file rules are offered to an Admin
once per session, and anyone else is told an Admin needs to update them. The window is replaced by stand-ins."""

import unittest
from types import SimpleNamespace

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace


class FileRulesPrompt(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.said, self.tasks = [], []
        app.repo = lambda: "/vault"
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        app.run_task = lambda work, text, **k: self.tasks.append(text)
        app.identity = SimpleNamespace(allows=lambda action: (True, ""))
        self.app = app
        rules = self.gui.file_rules.git_attributes
        replace(self, rules, "needs_update", lambda repo: (0, True))
        replace(self, rules, "read", lambda repo: "")

    def test_an_admin_is_asked_once_and_yes_updates(self):
        self.app._check_file_rules()
        self.app._check_file_rules()                          # the next refresh doesn't ask again
        asked = [c for c in self.box.calls if c[0] == "askyesno"]
        self.assertEqual(len(asked), 1)
        self.assertIn("Update the file rules now?", asked[0][1][1])
        self.assertEqual(len(self.tasks), 1)
        self.assertTrue(self.app.file_rules_outdated)          # until the update has run

    def test_saying_no_leaves_it_for_the_vault_menu(self):
        self.box.answer = False
        self.app._check_file_rules()
        self.assertEqual(self.tasks, [])
        self.assertIn("Vault > Update file rules", self.said[-1][0])

    def test_someone_who_may_not_is_told_who_can(self):
        self.app.identity = SimpleNamespace(allows=lambda action: (False, "Only an Admin can do that."))
        self.app._check_file_rules()
        self.assertFalse(any(c[0] == "askyesno" for c in self.box.calls))
        self.assertEqual(self.said[-1][1], "warn")
        self.assertIn("Admin or the Owner", self.said[-1][0])

    def test_an_up_to_date_vault_says_nothing(self):
        replace(self, self.gui.file_rules.git_attributes, "needs_update", lambda repo: (1, False))
        self.app._check_file_rules()
        self.assertEqual((self.box.calls, self.said, self.tasks), ([], [], []))
        self.assertFalse(self.app.file_rules_outdated)


if __name__ == "__main__":
    unittest.main()
