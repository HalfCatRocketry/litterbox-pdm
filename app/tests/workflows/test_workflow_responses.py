"""Tests for reject, withdraw and reassign (workflow_responses). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import PART
from litterbox.records import record_model
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import ENGINEER, MANAGER, PART2, QUALITY, Fixture
from litterbox.errors import LitterboxError


class TestRejectingWithdrawingReassigning(Fixture, unittest.TestCase):
    def test_rejecting_sends_the_whole_batch_back(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.sign_off, [PART, PART2])
        self.get_latest("Bea")
        self.do("Bea", workflow_responses.reject, [PART, PART2], "Wrong tolerance")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.pending, record.status), ({}, record_model.STATUS_IN_WORK))
            last = record.history[-1]
            self.assertEqual((last["event"], last["reason"], last["signed"]), ("release_rejected", "Wrong tolerance",
                                                                               ["Alex Smith"]))

    def test_a_reason_is_required_to_reject(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_responses.reject, [PART], "  ")

    def test_only_named_signers_or_admins_reject(self):
        self.request()
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Cy", workflow_responses.reject, [PART], "no")
        self.assertIn("named to sign", str(ctx.exception))
        self.assertTrue(self.record().pending)

    def test_the_requester_can_withdraw_but_other_members_cannot(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.withdraw, [PART])
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", workflow_responses.withdraw, [PART], "Changed my mind")
        self.assertEqual(self.record().pending, {})
        self.assertEqual(self.record().history[-1]["event"], "release_withdrawn")

    def test_after_a_withdrawal_a_new_request_can_be_made(self):
        self.request()
        self.do("Alex", workflow_responses.withdraw, [PART])
        self.request()
        self.assertTrue(self.record().pending)

    def test_the_requester_can_change_who_signs(self):
        self.set_template(rows=((QUALITY, MANAGER), (ENGINEER,)))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_responses.reassign, [PART], 0, "cy")
        slot = self.record().pending["slots"][0]
        self.assertEqual((slot["id"], slot["name"]), ("cy", "Cy Day"))
        self.assertEqual(self.record().history[-1]["event"], "workflow_reassigned")

    def test_reassigning_respects_the_rules(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_responses.reassign, [PART], 0, "cy")                # Cy has no Quality role
        self.assertIn("not active with the role", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.reassign, [PART], 0, "bea")
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_responses.reassign, [PART], 1, "alex")
        self.assertIn("already been given", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
