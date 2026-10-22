"""Tests for gui/logic/change_text.py (the parts table's Rev, Form, Fit, Function and Dispo columns) and
gui/logic/review_text.py (the Review window's buttons and words)."""

import unittest
from litterbox.core.part_number import PN
from litterbox.gui.logic import change_text
from litterbox.gui.logic import review_text
from litterbox.workflows import workflow_tasks

P1, P2 = PN("HCR", 1, 1), PN("HCR", 2, 1)


class TestChangeText(unittest.TestCase):
    def test_cells_show_boxes_dashes_and_the_dispo(self):
        asked = change_text.asks(P1, "release", "B", "A")
        self.assertEqual(change_text.cells(P1, "Bracket", "B", "A", {"changed": ["fit"], "disposition": "scrap"}, asked),
                         ["HCR-00001-001", "Bracket", "A → B", "☐", "☑", "☐", "Scrap"])
        self.assertEqual(change_text.cells(P1, "Bracket", "B", "A", None, asked)[-1], "Choose...")
        first = change_text.asks(P2, "release", "A", "")
        self.assertEqual(change_text.cells(P2, "Arm", "A", "", None, first)[2:], ["A", "—", "—", "—", "—"])
        void = change_text.asks(P2, "void", "A", "")
        self.assertEqual(change_text.cells(P2, "Arm", "A", "", None, void)[3:], ["—", "—", "—", "Choose..."])

    def test_ticking_and_choosing(self):
        change = change_text.toggled({}, "function")
        change = change_text.toggled(change, "form")
        self.assertEqual(change["changed"], ["form", "function"])
        self.assertEqual(change_text.toggled(change, "form")["changed"], ["function"])
        self.assertEqual(change_text.with_disposition(change, "rework")["disposition"], "rework")

    def test_missing_dispositions_and_what_is_kept(self):
        parts = [(P1, "B", "A"), (P2, "A", "")]
        self.assertEqual(change_text.missing_dispositions(parts, "release", {}), ["HCR-00001-001"])
        self.assertIn("Choose a Dispo for HCR-00001-001", change_text.missing_text(["HCR-00001-001"]))
        changes = {"HCR-00001-001": {"changed": ["fit"], "disposition": "scrap"}, "HCR-00002-001": {"changed": ["fit"]}}
        self.assertEqual(change_text.missing_dispositions(parts, "release", changes), [])
        self.assertEqual(change_text.kept(parts, "release", changes),
                         {"HCR-00001-001": {"changed": ["fit"], "disposition": "scrap"}})
        self.assertEqual(change_text.kept(parts, "reopen", changes), {})
        self.assertEqual([key for _label, key in change_text.disposition_choices()],
                         ["use_as_is", "rework", "scrap", "return_to_supplier"])


class TestReviewText(unittest.TestCase):
    def task(self, **changes):
        task = workflow_tasks.Task("b1", "release", [(P1, "Bracket", "B")], "Alex Smith", "2026-10-11T09:30:00Z",
                                   "", [{"text": "Quality", "name": "Bea", "done": False},
                                        {"text": "Manager", "name": "Cy", "done": True}], False, False,
                                   reason="", template_name="T1")
        for key, value in changes.items():
            setattr(task, key, value)
        return task

    def test_the_buttons_follow_the_hand_overs(self):
        self.assertEqual(review_text.buttons([0, 2], {}), {"approve": True, "reject": True, "reassign": False})
        self.assertEqual(review_text.buttons([0, 2], {0: "cy"}), {"approve": True, "reject": True, "reassign": False})
        self.assertEqual(review_text.buttons([0, 2], {0: "cy", 2: "dee"}),
                         {"approve": False, "reject": False, "reassign": True})
        self.assertEqual(review_text.buttons([], {}), {"approve": False, "reject": False, "reassign": False})
        self.assertEqual(review_text.kept([0, 2], {0: "cy"}), [2])

    def test_slot_words(self):
        task = self.task()
        self.assertEqual(review_text.slot_status(task.slots[0], 0, [0], {}), "Bea (you, waiting)")
        self.assertEqual(review_text.slot_status(task.slots[0], 0, [0], {0: "Cy Day"}),
                         "Bea → Cy Day (when you press Approve or Reassign)")
        self.assertEqual(review_text.slot_status(task.slots[1], 1, [0], {}), "✓ Cy (signed)")
        self.assertEqual(review_text.slot_status(task.slots[0], 0, [], {}), "Bea (waiting)")

    def test_summary_and_questions(self):
        lines = dict(review_text.summary_lines(self.task(reason="Drawing error"), local=False))
        self.assertEqual(lines, {"Workflow": "Release T1", "Asked by": "Alex Smith on 2026-10-11 09:30",
                                 "Reason": "Drawing error"})
        self.assertIn("Write why", review_text.reject_problem("  "))
        self.assertEqual(review_text.reject_problem("Too thin"), "")
        question = review_text.approve_question(self.task(), 1, {0: "Cy Day"})
        self.assertIn("Approve 1 sign-off", question)
        self.assertIn("Handed to someone else: Cy Day", question)
        self.assertIn("happens straight away", question)
        self.assertIn("Cy Day", review_text.reassign_question({0: "Cy Day"}))
        self.assertEqual(review_text.why_not(self.task(why_not_sign="x"), []), "x")
        self.assertEqual(review_text.why_not(self.task(), [0]), "")


class TestDetailsAndHistory(unittest.TestCase):
    """An old revision's Details say what to do with its parts; the history says what changed."""

    def setUp(self):
        from litterbox.records import record_model
        at = "2026-10-11T09:30:00Z"
        self.record = record_model.Record(P1, "Bracket", "Alex", at, revision="B", released_revision="B",
                                          status=record_model.STATUS_RELEASED)
        self.record.history = [
            {"event": "released", "by": "Alex", "at": at, "revision": "A"},
            {"event": "release_requested", "by": "Alex", "at": at, "revision": "B", "action": "release",
             "resubmitted": True, "changed": ["form"], "disposition": "scrap"},
            {"event": "released", "by": "Alex", "at": at, "revision": "B", "changed": ["form"]},
            {"event": "disposition", "by": "Alex", "at": at, "revision": "A", "disposition": "scrap",
             "reason": "Rev B released"}]

    def test_the_details_of_each_revision(self):
        from litterbox.gui.logic import part_details_text
        self.assertEqual(part_details_text.change_rows(self.record, "A", local=False),
                         [("Disposition", "Scrap (Rev B released; by Alex on 2026-10-11 09:30)")])
        self.assertEqual(part_details_text.change_rows(self.record, "B", local=False), [("Changed", "Form")])

    def test_the_history_words(self):
        from litterbox.gui.logic import history_text
        rows = history_text.format_history(self.record, local=False)
        self.assertEqual(rows[0][2:], ("Disposition", "Rev A parts: Scrap  -  Rev B released"))
        self.assertIn("changed: Form", rows[1][3])
        self.assertEqual(rows[2][2], "Release resubmitted")
        self.assertIn("Dispo: Scrap", rows[2][3])


if __name__ == "__main__":
    unittest.main()
