"""Tests for rejected requests (workflow_drafts, workflow_request.resubmit, workflow_responses.reject and withdraw) and
for handing your own sign-offs to someone else (workflow_responses.hand_over). Uses the two-user vault (Alex is the
Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need
Linux, macOS or WSL (or LITTERBOX_GIT_TESTS=1 on Windows)."""

import unittest
from tests.support.vault_fixture import PART
from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store
from litterbox.errors import LitterboxError
from litterbox.parts import part_status
from litterbox.parts import planning
from litterbox.records import record_model
from litterbox.team import team_store
from litterbox.workflows import workflow_drafts
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates
from tests.support.identities import identity_for
from tests.support.workflow_fixture import ENGINEER, MANAGER, PART2, QUALITY, Fixture

ECO = {"name": "Thicker bracket", "description": "Wall from 2 mm to 3 mm"}
RELEASE = workflow_templates.RELEASE


class TestDrafts(Fixture, unittest.TestCase):
    def reject(self, pns=(PART,), comment="Wrong tolerance"):
        self.get_latest("Bea")
        self.do("Bea", workflow_responses.reject, list(pns), comment)
        self.get_latest("Alex")

    def tasks(self, who, user="Alex", everything=False):
        rows = self.do(user, part_status.get_status)
        return workflow_tasks.tasks_from_rows(rows, identity_for(who, team_store.load(self.a)), everything=everything)

    def resubmit(self, batch, pns=(PART,), user="Alex", **kwargs):
        return self.do(user, workflow_request.resubmit, batch, list(pns), RELEASE, "T", ["bea", "alex"], **kwargs)

    def test_rejecting_makes_a_draft_for_whoever_asked(self):
        batch = self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.reject()
        record = self.record()
        self.assertEqual(record.pending, {})
        self.assertEqual((record.draft["id"], record.draft["rejected"]["comment"], record.draft["rejected"]["by_id"]),
                         (batch, "Wrong tolerance", "bea"))
        self.assertEqual(record.history[-1]["event"], record_model.EVENT_RELEASE_REJECTED)
        self.assertEqual(self.tasks("bea", "Bea"), [])                       # gone from the signers' My Tasks
        (task,) = self.tasks("alex")
        self.assertEqual((task.draft, task.mine, task.can_withdraw, task.can_sign, task.rejected["comment"]),
                         (True, True, True, False, "Wrong tolerance"))
        self.assertTrue(workflow_tasks.needs_me(task))
        (seen,) = self.tasks("cy", everything=True)                         # still listed in All Workflows
        self.assertTrue(seen.draft)

    def test_a_draft_part_is_free_to_check_out_but_not_to_go_into_anything_else(self):
        self.request()
        self.reject()
        record = self.record()
        self.assertEqual(record.status, record_model.STATUS_IN_WORK)
        self.assertNotIn("sign-offs", " ".join(self.do("Alex", planning.release_plan, PART).problems))
        self.assertIn("rejected workflow", " ".join(self.do("Alex", planning.release_plan, PART).problems))
        with self.assertRaises(LitterboxError) as ctx:
            self.request()
        self.assertIn("rejected workflow", str(ctx.exception))

    def test_rejecting_keeps_the_eco_open_and_resubmitting_carries_it_on(self):
        self.make_rev_b()
        self.set_template(eco=True)
        change = {str(PART): {"changed": ["form"], "disposition": "scrap"}}
        batch = self.do("Alex", workflow_request.request, [PART], RELEASE, "T", ["bea", "alex"], eco=ECO,
                        changes=change)
        self.reject()
        eco = eco_store.load(self.a, "ECO-0001")
        self.assertEqual((eco.status, eco.history[-1]["event"], eco.history[-1]["comment"]),
                         (eco_model.OPEN, "rejected", "Wrong tolerance"))
        self.assertEqual(self.record().draft["change"], change[str(PART)])
        self.resubmit(batch, eco={"name": "Thicker bracket, again", "description": "Wall to 3.5 mm"},
                      changes={str(PART): {"changed": ["fit"], "disposition": "rework"}})
        eco = eco_store.load(self.a, "ECO-0001")
        self.assertEqual((eco.status, eco.name, eco.history[-1]["event"]),
                         (eco_model.OPEN, "Thicker bracket, again", "resubmitted"))
        self.assertEqual((eco.parts[0]["changed"], eco.parts[0]["disposition"]), (["fit"], "rework"))
        self.assertEqual(eco_store.numbers(self.a), ["ECO-0001"])
        self.assertEqual(self.record().pending["eco"], "ECO-0001")

    def test_resubmitting_puts_the_request_back_with_the_same_id(self):
        batch = self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.reject()
        self.assertEqual(self.resubmit(batch), batch)
        record = self.record()
        self.assertEqual((record.draft, record.pending["id"], record.pending["signoffs"]), ({}, batch, []))
        self.assertTrue(record.history[-1]["resubmitted"])
        self.get_latest("Bea")
        (task,) = self.tasks("bea", "Bea")
        self.assertTrue(task.can_sign)

    def test_parts_taken_out_when_resubmitting_leave_the_draft(self):
        self.second_part()
        batch = self.request(pns=(PART, PART2))
        self.reject(pns=(PART, PART2))
        self.resubmit(batch, pns=(PART,))
        self.assertEqual(self.record(PART).pending["parts"], [str(PART)])
        other = self.record(PART2)
        self.assertEqual((other.pending, other.draft), ({}, {}))
        self.assertEqual(other.history[-1]["reason"], workflow_drafts.TAKEN_OUT)

    def test_only_whoever_asked_resubmits(self):
        batch = self.request()
        self.reject()
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_request.resubmit, batch, [PART], RELEASE, "T", ["bea", "alex"])
        self.assertIn("person who asked", str(ctx.exception))

    def test_withdrawing_a_draft_ends_it_and_its_eco(self):
        self.make_rev_b()
        self.set_template(eco=True)
        self.do("Alex", workflow_request.request, [PART], RELEASE, "T", ["bea", "alex"], eco=ECO,
                changes={str(PART): {"disposition": "use_as_is"}})
        self.reject()
        self.do("Alex", workflow_responses.withdraw, [PART], "Not needed")
        record = self.record()
        self.assertEqual((record.pending, record.draft), ({}, {}))
        self.assertEqual(record.history[-1]["event"], record_model.EVENT_RELEASE_WITHDRAWN)
        self.assertEqual(eco_store.load(self.a, "ECO-0001").status, eco_model.WITHDRAWN)
        self.request(eco=ECO)                                                # free for a new request
        self.assertEqual(self.record().pending["eco"], "ECO-0002")


class TestHandingOver(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.set_template(rows=((QUALITY, MANAGER), (ENGINEER,)))
        self.do("Alex", workflow_request.request, [PART], RELEASE, "T", ["bea", "alex"])
        self.get_latest("Bea")

    def test_a_signer_hands_their_sign_off_to_someone_else(self):
        self.do("Bea", workflow_responses.hand_over, [PART], {0: "cy"})
        slot = self.record().pending["slots"][0]
        self.assertEqual((slot["id"], slot["name"]), ("cy", "Cy Day"))
        last = self.record().history[-1]
        self.assertEqual((last["event"], last["handed_over"]), (record_model.EVENT_REASSIGNED, True))
        self.do("Alex", workflow_signoff.sign_off, [PART])
        result = self.do("Cy", workflow_signoff.sign_off, [PART])
        self.assertEqual(result.completed, [PART])

    def test_only_your_own_sign_offs_can_be_handed_over(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_responses.hand_over, [PART], {0: "cy"})
        self.assertIn("named for you", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.hand_over, [PART], {0: "bea"})
        self.assertIn("other than yourself", str(ctx.exception))

    def test_the_new_signer_must_hold_the_role(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.hand_over, [PART], {0: "alex"})       # Alex has neither role
        self.assertIn("not active with the role", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
