"""Tests for My Tasks (workflow_tasks) and describing a pending request (signoff_slots). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL."""

import unittest
from types import SimpleNamespace
from tests.support.vault_fixture import PART
from litterbox.team import team_identity
from litterbox.team import team_store
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_signoff
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import ENGINEER, PART2, Fixture
from litterbox.parts import part_status
from tests.support.identities import identity_for


class TestTasks(Fixture, unittest.TestCase):
    def rows(self, user="Alex"):
        return self.do(user, part_status.get_status)

    def tasks(self, who, user="Alex"):
        return workflow_tasks.tasks_from_rows(self.rows(user), identity_for(who, team_store.load(self.a)))

    def test_nothing_pending_means_no_tasks(self):
        self.assertEqual(self.tasks("alex"), [])

    def test_a_named_signer_can_sign_and_reject(self):
        self.request()
        (t,) = self.tasks("bea", "Bea")
        self.assertEqual((t.can_sign, t.can_reject, t.can_withdraw, t.can_override, t.can_reassign),
                         (True, True, False, False, False))
        self.assertEqual(t.label, str(PART))
        self.assertEqual([s["name"] for s in t.slots], ["Bea Jones", "Alex Smith"])

    def test_someone_not_named_only_looks_in_all_workflows(self):
        self.request()
        self.assertEqual(self.tasks("cy"), [])                         # not in their My Tasks
        (t,) = workflow_tasks.tasks_from_rows(self.rows(), identity_for("cy", team_store.load(self.a)), everything=True)
        self.assertEqual((t.can_sign, t.can_reject, t.can_complete), (False, False, False))
        self.assertIn("not one of the people named", t.why_not_sign)

    def test_the_requester_can_withdraw_and_reassign_and_an_admin_can_override(self):
        self.request()
        (t,) = self.tasks("alex")
        self.assertEqual((t.can_withdraw, t.can_override, t.can_reassign, t.mine), (True, True, True, True))

    def test_a_batch_is_one_task_and_done_means_signed_on_every_part(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        (t,) = self.tasks("alex")
        self.assertEqual((len(t.parts), t.label), (2, f"{PART} +1 more"))
        self.do("Alex", workflow_signoff.sign_off, [PART])                           # only one of the two parts
        (t,) = self.tasks("alex")
        self.assertTrue(t.can_sign)                                    # still something to sign on the other
        self.assertFalse(t.slots[1]["done"])

    def test_an_approved_request_waits_on_its_requester_to_complete(self):
        self.set_template(workflow_templates.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.MAKE_COTS, "T", ["alex"])
        self.do("Alex", workflow_signoff.sign_off, [PART])
        (t,) = self.tasks("alex")
        self.assertEqual((t.ready, t.can_complete, workflow_tasks.count_for_me([t])), (True, True, 1))

    def test_nobody_can_act_without_a_team_identity(self):
        self.request()
        ident = SimpleNamespace(state=team_identity.NOT_LISTED, person=None, directory=None)
        (t,) = workflow_tasks.tasks_from_rows(self.rows(), ident, everything=True)
        self.assertFalse(any((t.can_sign, t.can_reject, t.can_complete, t.can_withdraw, t.can_override)))

    def test_things_waiting_on_me_come_first(self):
        self.second_part()
        self.request(pns=(PART,), assign=("cy", "alex")) if False else None
        self.set_template()
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_request.request, [PART2], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_signoff.sign_off, [PART2])
        tasks = self.tasks("alex")
        self.assertEqual([str(t.pns[0]) for t in tasks], [str(PART), str(PART2)])


class TestDescribing(unittest.TestCase):
    def pending(self, signed=()):
        return {"action": "release", "slots": [{"roles": ["Quality"], "id": "bea", "name": "Bea"},
                                               {"roles": ["Manager", "Chief"], "id": "cy", "name": "Cy"}],
                "signoffs": [{"slot": i} for i in signed]}

    def test_progress_text(self):
        self.assertEqual(signoff_slots.describe_pending(self.pending()), "Release pending 0/2: waiting on Bea, Cy")
        self.assertEqual(signoff_slots.describe_pending(self.pending([0])), "Release pending 1/2: waiting on Cy")
        self.assertEqual(signoff_slots.describe_pending(self.pending([0, 1])), "Release approved - ready to complete")
        self.assertEqual(signoff_slots.waiting_on(self.pending([0])), ["Manager or Chief (Cy)"])

    def test_open_slots_and_may_sign(self):
        p = self.pending([0])
        person = SimpleNamespace(id="cy")
        self.assertEqual(signoff_slots.open_slots(p, "cy"), [1])
        self.assertEqual(signoff_slots.open_slots(p, "bea"), [])
        self.assertEqual(signoff_slots.may_sign(p, person), (True, ""))
        self.assertIn("already signed", signoff_slots.may_sign(p, SimpleNamespace(id="bea"))[1])
        self.assertIn("not one of the people", signoff_slots.may_sign(p, SimpleNamespace(id="zed"))[1])


if __name__ == "__main__":
    unittest.main()
