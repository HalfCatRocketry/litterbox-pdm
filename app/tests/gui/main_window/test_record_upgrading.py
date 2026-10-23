"""Tests for gui/main_window/record_upgrading.py: after a refresh, a vault whose records need upgrading is offered to
an Admin once per session, and anyone else is told an Admin needs to do it. The window is replaced by stand-ins."""

import unittest
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.gui.logic import record_upgrade_text
from litterbox.records import record_migrations
from litterbox.vault.record_upgrade import Plan, Result
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace

STEP = record_migrations.Step("0.6.0", "Costs keep their currency", lambda data: data)


class RecordUpgradePrompt(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.said, self.tasks = [], []
        app.repo = lambda: "/vault"
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        app.run_task = lambda work, text, on_success=None, **k: self.tasks.append((k.get("label"), on_success))
        app.identity = SimpleNamespace(allows=lambda action: (True, ""))
        self.app = app
        self.upgrade = self.gui.record_upgrading.record_upgrade
        replace(self, self.upgrade, "needs_upgrade", lambda repo: True)

    def plan(self, **fields):
        values = dict(outdated={PN("HCR", 1, 1): 1, PN("HCR", 2, 1): 1}, steps=[(STEP, 2)], raise_minimum="0.6.0")
        values.update(fields)
        return Plan(**values)

    def test_an_admin_is_asked_once_and_yes_upgrades(self):
        self.app._check_record_upgrade()
        self.app._check_record_upgrade()                      # the next refresh doesn't ask again
        self.assertEqual([label for label, _done in self.tasks], ["Looking at the records"])
        self.tasks[0][1](self.plan())                           # the plan arrives: the question
        asked = [c for c in self.box.calls if c[0] == "askyesno"]
        self.assertEqual(len(asked), 1)
        self.assertIn("Costs keep their currency (2 records)", asked[0][1][1])
        self.assertIn("Litterbox 0.6.0 or newer", asked[0][1][1])
        self.assertEqual(self.tasks[-1][0], "Upgrading the records")
        self.assertTrue(self.app.records_outdated)              # until the upgrade has run
        self.tasks[-1][1](Result(rewritten=2))
        self.assertFalse(self.app.records_outdated)
        self.assertEqual(self.said[-1], ("2 records upgraded", "normal"))

    def test_saying_no_leaves_it_for_the_vault_menu(self):
        self.box.answer = False
        self.app._check_record_upgrade()
        self.tasks[0][1](self.plan())
        self.assertEqual(len(self.tasks), 1)
        self.assertIn("Vault > Upgrade records", self.said[-1][0])

    def test_checked_out_records_are_named_and_keep_the_menu_entry(self):
        self.app.upgrade_records()
        self.tasks[0][1](self.plan(checked_out=[PN("HCR", 2, 1)]))
        self.assertIn("Checked out, so left until they are checked in: HCR-00002-001.",
                      [c for c in self.box.calls if c[0] == "askyesno"][0][1][1])
        self.tasks[-1][1](Result(rewritten=1, checked_out=[PN("HCR", 2, 1)]))
        self.assertTrue(self.app.records_outdated)
        self.assertIn("1 checked-out record left until checked in", self.said[-1][0])

    def test_someone_who_may_not_is_told_who_can(self):
        self.app.identity = SimpleNamespace(allows=lambda action: (False, "Only an Admin can do that."))
        self.app._check_record_upgrade()
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.said[-1], (record_upgrade_text.ASK_AN_ADMIN, "warn"))

    def test_an_up_to_date_vault_says_nothing(self):
        replace(self, self.upgrade, "needs_upgrade", lambda repo: False)
        self.app._check_record_upgrade()
        self.assertEqual((self.box.calls, self.said, self.tasks), ([], [], []))
        self.assertFalse(self.app.records_outdated)

    def test_nothing_left_to_do_by_the_time_the_plan_arrives(self):
        self.app.upgrade_records()
        self.tasks[0][1](self.plan(outdated={}, steps=[], raise_minimum=""))
        self.assertEqual(self.said[-1][0], record_upgrade_text.UP_TO_DATE)
        self.assertFalse(any(c[0] == "askyesno" for c in self.box.calls))


if __name__ == "__main__":
    unittest.main()
