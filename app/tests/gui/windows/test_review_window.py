"""Tests for My Tasks' Review window (gui/dialogs/workflow/review_dialog.py). The window is built on stand-ins
(tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from types import SimpleNamespace
from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes, replace
from litterbox.core.part_number import PN
from litterbox.team import team_model
from litterbox.workflows import workflow_tasks

P1 = PN("HCR", 1, 1)


class ReviewWindow(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.directory = team_model.Directory(
            [team_model.Person("alex", "Alex", "", ["Alex"], "owner", ["Quality"]),
             team_model.Person("bea", "Bea", "", ["Bea"], "member", ["Quality"])], ["Quality"])
        self.task = workflow_tasks.Task(
            "b1", "release", [(P1, "Bracket", "B")], "Cy", "2026-10-11T09:30:00Z", "",
            [{"text": "Quality", "name": "Alex", "id": "alex", "done": False, "roles": ["Quality"]},
             {"text": "Quality", "name": "Alex", "id": "alex", "done": False, "roles": ["Quality"]}], False, False,
            template_name="T1", my_slots=[0, 1], earlier={"HCR-00001-001": "A"},
            changes={"HCR-00001-001": {"changed": ["fit"], "disposition": "rework"}})
        self.opened = []
        self.dialog = self.gui.review_dialog.ReviewDialog(FakeParent(), self.task, self.directory, "alex",
                                                          on_open=lambda *a: self.opened.append(a))
        self.dialog.comment_var.set("")
        self.states = {}
        for key, button in self.dialog.answer_buttons.items():
            button.configure = lambda key=key, **kw: self.states.__setitem__(key, kw.get("state"))
        self.dialog._update_buttons()

    def hand(self, index, person="bea"):
        replace(self, self.gui.reassign_dialog, "ReassignDialog",
                lambda *a, **k: SimpleNamespace(show=lambda: (index, person)))
        self.dialog._hand(index)
        self.dialog._update_buttons()

    def test_the_parts_show_what_changed_and_can_be_opened(self):
        self.assertEqual(self.dialog.parts_tree.rows["HCR-00001-001"]["values"][2:],
                         ["A → B", "☐", "☑", "☐", "Rework"])
        self.dialog.parts_tree.selection_set("HCR-00001-001")
        self.dialog._open(False, "drawing")
        self.dialog._open(True, "pdf")
        self.assertEqual(self.opened, [(P1, "B", "drawing"), (P1, "A", "pdf")])

    def test_handing_over_some_keeps_approve_and_all_switches_to_reassign(self):
        self.assertEqual(self.states, {"approve": "normal", "reject": "normal", "reassign": "disabled"})
        self.hand(0)
        self.assertEqual(self.states, {"approve": "normal", "reject": "normal", "reassign": "disabled"})
        self.hand(1)
        self.assertEqual(self.states, {"approve": "disabled", "reject": "disabled", "reassign": "normal"})
        self.dialog._answer("reassign")
        self.assertEqual(self.dialog.result, {"answer": "reassign", "handed": {0: "bea", 1: "bea"}, "comment": ""})

    def test_undo_takes_a_hand_over_back(self):
        self.hand(0)
        self.dialog._hand(0)
        self.assertEqual(self.dialog.handed, {})

    def test_approve_keeps_the_hand_overs_and_reject_needs_a_comment(self):
        self.hand(1)
        self.dialog._answer("reject")
        self.assertIsNone(self.dialog.result)
        self.dialog.comment_var.set("  Looks   good ")
        self.dialog._answer("approve")
        self.assertEqual(self.dialog.result, {"answer": "approve", "handed": {1: "bea"}, "comment": "Looks good"})

    def test_reject_drops_the_hand_overs(self):
        self.hand(1)
        self.dialog.comment_var.set("Too thin")
        self.dialog._answer("reject")
        self.assertEqual(self.dialog.result, {"answer": "reject", "handed": {}, "comment": "Too thin"})


if __name__ == "__main__":
    unittest.main()
