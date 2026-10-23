"""Tests for gui/logic/task_text.py: My Tasks and workflow requests."""

import unittest
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import task_text


class TestWorkflowText(unittest.TestCase):
    def template(self):
        from litterbox.workflows import workflow_templates
        return workflow_templates.Template("release", "T1", [workflow_templates.Row(["Quality"]), workflow_templates.Row(["Manager", "Chief"])])

    def slots(self):
        return [{"roles": ["Quality"], "id": "bea", "name": "Bea Jones"},
                {"roles": ["Manager", "Chief"], "id": "cy", "name": "Cy Day"},
                {"roles": ["Analysis"], "id": "dee", "name": "Dee", "extra": True}]

    def test_the_request_question_lists_parts_and_signers(self):
        text = task_text.request_confirm_text("release", [("HCR-00001-001", "Upright"), ("HCR-00002-001", "Arm")],
                                          self.template(), self.slots())
        self.assertIn("Start the Release workflow (T1)", text)
        self.assertIn("  HCR-00001-001  Upright\n  HCR-00002-001  Arm", text)
        self.assertIn("  Quality: Bea Jones\n", text)
        self.assertIn("  Manager or Chief: Cy Day\n", text)
        self.assertIn("  Analysis (extra): Dee", text)
        self.assertIn("as soon as the last person signs", text)

    def test_make_cots_happens_at_the_last_sign_off_and_reasons_and_notes_show(self):
        text = task_text.request_confirm_text("make_cots", [("HCR-00001-001", "Upright")], self.template(), self.slots(),
                                          "Because", ["Nobody has Quality."])
        self.assertIn("as soon as the last person signs", text)
        self.assertIn("Reason: Because", text)
        self.assertIn("Nobody has Quality.", text)

    def test_a_resubmitted_request_says_everyone_signs_again_and_its_eco_carries_on(self):
        text = task_text.request_confirm_text("release", [("HCR-00001-001", "Upright")], self.template(), self.slots(),
                                              eco={"name": "Thicker wall", "description": "Why"}, resubmit=True)
        self.assertIn("Resubmit the Release workflow (T1)", text)
        self.assertIn("(everyone signs again)", text)
        self.assertIn("ECO) carries on: Thicker wall", text)

    def test_standard_actions_route_pending_parts_to_their_buttons(self):
        for action in ("open", "open_drawing", "references", "release", "reopen", "void", "make_cots"):
            self.assertIn("pending", action_rules.ALLOWED_KINDS[action])
        for action in ("checkout", "checkin", "revise", "cancel_revision", "undo"):
            self.assertNotIn("pending", action_rules.ALLOWED_KINDS[action])

    def test_task_table_detail_and_button_text(self):
        from types import SimpleNamespace
        task = SimpleNamespace(id="ab12", label="HCR-00001-001 +1 more", action="reopen",
                               parts=[("HCR-00001-001", "Upright", "A"), ("HCR-00002-001", "Arm", "A")],
                               requested_by="Alex Smith", requested_at="2026-10-11T00:00:00Z",
                               summary="Unrelease pending 0/1: waiting on Cy", reason="Drawing error", eco="ECO-0003",
                               slots=[{"text": "Manager", "name": "Cy", "done": False},
                                      {"text": "Quality", "name": "Bea", "done": True}], draft=False, involved=True)
        (iid, values), = task_text.tasks_table([task], local=False)
        self.assertEqual(iid, "ab12")
        self.assertEqual(values, ("HCR-00001-001 +1 more", "2 parts", "Unrelease", "Alex Smith", "2026-10-11 00:00",
                                  "Unrelease pending 0/1: waiting on Cy"))
        detail = task_text.task_detail(task)
        self.assertIn("HCR-00001-001, HCR-00002-001", detail)
        self.assertIn("… Manager: Cy (waiting)", detail)
        self.assertIn("✓ Quality: Bea", detail)
        self.assertIn("ECO: ECO-0003", detail)
        self.assertIn("Reason: Drawing error", detail)
        from litterbox.workflows import workflow_tasks
        mine = workflow_tasks.Task("ab12", "release", [], "", "", "", [], False, True, involved=True)
        self.assertTrue(task_text.button_states(mine)["review"])
        self.assertFalse(task_text.button_states(mine)["complete"])
        self.assertFalse(any(task_text.button_states(None).values()))

    def test_a_rejected_request_says_who_rejected_it_and_why(self):
        from types import SimpleNamespace
        task = SimpleNamespace(parts=[("HCR-00001-001", "Upright", "B")], draft=True, eco="ECO-0003",
                               rejected={"by": "Bea Jones", "at": "2026-10-11T00:00:00Z", "comment": "Wrong tolerance"})
        detail = task_text.task_detail(task, local=False)
        self.assertIn("Rejected by Bea Jones on 2026-10-11 00:00: Wrong tolerance", detail)
        self.assertIn("resubmit", detail)
        self.assertIn("ECO: ECO-0003", detail)
        self.assertEqual(task_text.rejection_text({"by": "Bea", "comment": "No", "override": True}),
                         "Rejected by Bea (Admin override): No")

    def test_signoff_result_text_is_empty_unless_something_failed(self):
        from types import SimpleNamespace
        self.assertEqual(task_text.signoff_result_text(SimpleNamespace(errors={})), ("", False))
        text, warn = task_text.signoff_result_text(SimpleNamespace(errors={"HCR-00001-001": "offline"}))
        self.assertTrue(warn)
        self.assertIn("HCR-00001-001: offline", text)

    def test_people_drop_downs(self):
        from litterbox.team import team_model
        directory = team_model.Directory(
            [team_model.Person("a", "Alex", "", [], "owner", ["Quality"]), team_model.Person("b", "Alex", "", [], "member",
                                                                                      ["Manager"]),
             team_model.Person("c", "Cy", "", [], "member", ["Quality"], active=False)], ["Quality", "Manager"])
        self.assertEqual(task_text.row_choices(directory, ["Quality", "Manager"]), [("Alex (a)", "a"), ("Alex (b)", "b")])
        self.assertEqual(task_text.row_choices(directory, ["Quality"], "a", False), [])
        self.assertEqual(task_text.row_choices(directory, ["Manager"]), [("Alex", "b")])


if __name__ == "__main__":
    unittest.main()
