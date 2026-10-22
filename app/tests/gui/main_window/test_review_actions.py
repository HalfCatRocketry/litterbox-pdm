"""Tests for My Tasks' Review in the main window: approving, rejecting and handing over sign-offs, and changing,
resubmitting or withdrawing a rejected request. The window itself is replaced by stand-ins
(tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import replace
from tests.gui.main_window.test_task_actions import WorkflowSetup


class ReviewWiring(WorkflowSetup):
    def review(self, answer):
        """Review answers `answer`; the arguments it was opened with are kept in self.reviewed."""
        self.reviewed = []
        replace(self, self.gui.review_dialog, "ReviewDialog",
                lambda parent, task, directory, my_id, eco, on_open=None: self.reviewed.append((task, my_id, eco))
                or self.SimpleNamespace(show=lambda: answer))

    def test_approving_passes_the_comment_and_reports_a_failure(self):
        self.review({"answer": "approve", "handed": {}, "comment": "Looks right"})
        seen = []
        replace(self, self.gui.workflow_signoff, "sign_off", lambda repo, pns, comment: seen.append((pns, comment)) or "result")
        self.app.task_review(self.task())
        work, done, on_success = self.tasks.pop()
        result, files = work()
        self.assertEqual(result, "result")
        self.assertEqual(seen, [(["HCR-00001-001"], "Looks right")])
        self.assertEqual(self.made_after, [["HCR-00001-001"]])     # whatever it released gets its STEP and PDF
        on_success((self.SimpleNamespace(completed=[], errors={"HCR-00001-001": "offline"}), files))
        self.assertIn("offline", self.shown("showwarning")[0][1][1])
        on_success((self.SimpleNamespace(completed=["HCR-00001-001"], errors={}), files))
        self.assertIn("Release done on 1 part", self.app.note)

    def test_closing_the_review_does_nothing(self):
        self.review(None)
        self.app.task_review(self.task())
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.reviewed[0][1:], ("alex", None))

    def test_approving_hands_over_the_reassigned_sign_offs_first(self):
        self.review({"answer": "approve", "handed": {1: "bea"}, "comment": ""})
        calls = []
        replace(self, self.gui.workflow_responses, "hand_over", lambda repo, pns, people: calls.append(("hand", people)))
        replace(self, self.gui.workflow_signoff, "sign_off", lambda repo, pns, comment: calls.append(("sign", comment)))
        self.app.task_review(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(calls, [("hand", {1: "bea"}), ("sign", "")])

    def test_reassign_only_hands_over(self):
        self.review({"answer": "reassign", "handed": {0: "bea"}, "comment": ""})
        calls = []
        replace(self, self.gui.workflow_responses, "hand_over", lambda repo, pns, people: calls.append((pns, people)))
        self.app.task_review(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(calls, [(["HCR-00001-001"], {0: "bea"})])

    def test_rejecting_sends_the_comment(self):
        self.review({"answer": "reject", "handed": {}, "comment": "Missing tolerance"})
        seen = []
        replace(self, self.gui.workflow_responses, "reject", lambda repo, pns, reason: seen.append((pns, reason)))
        self.app.task_review(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], "Missing tolerance")])

    def test_the_review_shows_the_eco(self):
        self.review(None)
        eco = self.SimpleNamespace(number="ECO-0001", name="Thicker", description="")
        replace(self, self.gui.eco_store, "load", lambda repo, number: eco)
        self.app.task_review(self.task(eco="ECO-0001"))
        self.assertIs(self.reviewed[0][2], eco)

    def draft_task(self):
        return self.task(draft=True, eco="", template_name="T1", reason="", document="",
                         parts=[("HCR-00001-001", "Upright", "B")],
                         slots=[{"text": "Quality", "name": "Bea", "id": "bea", "done": False, "roles": ["Quality"]}],
                         changes={"HCR-00001-001": {"changed": ["form"], "disposition": "scrap"}},
                         rejected={"by": "Bea", "at": "2026-10-11T00:00:00Z", "comment": "Too thin"})

    def test_a_rejected_request_opens_filled_in_and_is_resubmitted(self):
        self.app.rows_by_pn = {"HCR-00001-001": self.SimpleNamespace(pn="HCR-00001-001", name="Upright", kind="ok",
                                                                     revision="B", released_revision="A")}
        self.app.jobs = self.SimpleNamespace(pending_parts=lambda: {})
        opened = []
        answer = {"template": "T1", "assignments": ["bea"], "extras": [], "reason": "", "parts": ["HCR-00001-001"],
                  "eco": None, "changes": {"HCR-00001-001": {"changed": ["fit"], "disposition": "scrap"}}}

        class Dialog:
            def __init__(inner, parent, action, parts, templates, directory, my_id, addable, draft=None):
                opened.append((parts, draft))

            def show(inner):
                return answer

        replace(self, self.gui.request_dialog, "WorkflowRequestDialog", Dialog)
        calls = []
        replace(self, self.gui.workflow_request, "resubmit", lambda *a: calls.append(a))
        self.app.task_review(self.draft_task())
        (parts, draft), = opened
        self.assertEqual(parts, [("HCR-00001-001", "Upright", "B", "A")])
        self.assertEqual((draft["people"], draft["changes"], draft["rejected"]["comment"]),
                         (["bea"], {"HCR-00001-001": {"changed": ["form"], "disposition": "scrap"}}, "Too thin"))
        self.tasks.pop()[0]()
        self.assertEqual(calls, [("C:/vault", "b1", ["HCR-00001-001"], "release", "T1", ["bea"], [], "", None, None,
                                  answer["changes"])])

    def test_a_rejected_request_can_be_withdrawn_from_its_window(self):
        self.app.rows_by_pn = {}
        self.app.jobs = self.SimpleNamespace(pending_parts=lambda: {})
        replace(self, self.gui.request_dialog, "WorkflowRequestDialog",
                lambda *a, **k: self.SimpleNamespace(show=lambda: {"withdraw": True}))
        gone = []
        replace(self, self.gui.workflow_responses, "withdraw", lambda repo, pns: gone.append(pns))
        self.app.task_review(self.draft_task())
        self.tasks.pop()[0]()
        self.assertEqual(gone, [["HCR-00001-001"]])


if __name__ == "__main__":
    unittest.main()
