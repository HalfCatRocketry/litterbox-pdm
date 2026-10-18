"""Tests for signing, completing and overriding (workflow_signoff). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL."""

import unittest
from unittest import mock
from tests.support.vault_fixture import DRW, PART, PRT, git
from litterbox.records import record_model
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_signoff
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import CHIEF, ENGINEER, MANAGER, PART2, Fixture
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.parts import part_status
from litterbox.git import runner


class TestSigning(Fixture, unittest.TestCase):
    def test_the_last_signature_releases(self):
        self.request()
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)
        self.get_latest("Bea")
        r = self.do("Bea", workflow_signoff.sign_off, [PART], "Looks good")
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_RELEASED, "A", {}))
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_the_trail_is_kept_in_approvals(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.get_latest("Bea")
        self.do("Bea", workflow_signoff.sign_off, [PART], "Looks good")
        entry = self.record().approvals[-1]
        self.assertEqual((entry["action"], entry["template_name"], entry["requested_by"]), ("release", "T", "Alex Smith"))
        self.assertEqual([(e["id"], e["slot"]) for e in entry["signoffs"]], [("alex", 1), ("bea", 0)])
        self.assertEqual(entry["signoffs"][1]["comment"], "Looks good")
        self.assertEqual(sorted(entry["files"]), [DRW, PRT])
        released = [e for e in self.record().history if e["event"] == "released"][-1]
        self.assertEqual(released["signoffs"], ["Alex Smith", "Bea Jones"])

    def test_a_batch_is_uploaded_once_per_step_not_once_per_part(self):
        self.second_part()
        self.set_template()
        seen, real = [], runner.run

        def recording(command, repo, quiet=False):
            seen.append(" ".join(command))
            return real(command, repo, quiet)

        replace_run = mock.patch.object(runner, "run", recording)
        with replace_run:
            self.request(pns=(PART, PART2))                       # one upload for the request
            requested = sum(1 for c in seen if c == "git push")
            self.do("Alex", workflow_signoff.sign_off, [PART, PART2])           # one for Alex's signatures
            self.get_latest("Bea")
            self.do("Bea", workflow_signoff.sign_off, [PART, PART2])            # one for hers, one for the release itself
        self.assertEqual(requested, 1)
        self.assertEqual(sum(1 for c in seen if c == "git push"), 4)
        self.assertEqual(sum(1 for c in seen if c.startswith("git commit")), 4)      # one commit per step, not per part
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_a_batch_is_signed_once_for_every_part(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.sign_off, [PART, PART2])
        self.get_latest("Bea")
        r = self.do("Bea", workflow_signoff.sign_off, [PART, PART2])
        self.assertEqual(sorted(map(str, r.completed)), sorted(map(str, [PART, PART2])))
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_signing_again_or_when_not_named_does_nothing(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertIn("nothing for you to sign", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Cy", workflow_signoff.sign_off, [PART])

    def test_one_person_named_twice_signs_both_at_once(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)), same=True)
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["alex", "alex"])
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])

    def test_a_failed_completion_keeps_the_signature_and_can_be_finished_later(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.get_latest("Bea")
        real = workflow_signoff._finish_many
        workflow_signoff._finish_many = lambda repo, pns, **k: (_ for _ in ()).throw(LitterboxError("offline"))
        try:
            r = self.do("Bea", workflow_signoff.sign_off, [PART])
        finally:
            workflow_signoff._finish_many = real
        self.assertEqual((r.signed, r.completed, r.errors), ([PART], [], {PART: "offline"}))
        self.get_latest("Alex")
        row = next(x for x in self.do("Alex", part_status.get_status) if x.pn == PART)
        self.assertEqual((row.kind, row.state), ("pending", "Release approved - ready to complete"))
        self.assertEqual(self.do("Alex", workflow_signoff.complete, PART), [DRW, PRT])
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_completing_before_everyone_signed_is_refused(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_signoff.complete, PART)
        self.assertIn("Quality (Bea Jones)", str(ctx.exception))

    def test_a_file_changed_since_the_request_stops_signing(self):
        self.request()
        self.get_latest("Bea")
        (self.b / PRT).chmod(0o644)
        (self.b / PRT).write_bytes(b"someone sneaked a change in")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_signoff.sign_off, [PART])
        self.assertIn("different from the file", str(ctx.exception))
        git(self.b, "checkout", "--", str(PRT))

    def test_reopen_completes_automatically(self):
        self.do("Alex", lifecycle.release, PART)
        self.set_template(workflow_templates.REOPEN, rows=((MANAGER, CHIEF),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.REOPEN, "T", ["cy"], reason="Drawing error")
        r = self.do("Cy", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_IN_WORK, "", {}))
        self.assertEqual([e for e in record.history if e["event"] == "reopened"][-1]["reason"], "Drawing error")
        self.assertEqual(record.approvals[-1]["reason"], "Drawing error")

    def test_void_completes_automatically(self):
        self.set_template(workflow_templates.VOID, rows=((MANAGER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.VOID, "T", ["cy"], reason="Not needed")
        r = self.do("Cy", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        self.assertEqual(self.record().status, record_model.STATUS_VOID)

    def test_make_cots_waits_for_someone_to_complete_it(self):
        self.set_template(workflow_templates.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.MAKE_COTS, "T", ["alex"])
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertTrue(signoff_slots.is_complete(self.record().pending))
        self.assertFalse(self.record().cots)
        self.do("Alex", workflow_signoff.complete, PART)
        self.assertTrue(self.record().cots)
        self.assertEqual(self.record().pending, {})


class TestOverride(Fixture, unittest.TestCase):
    def test_a_member_cannot_override(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_signoff.override, [PART], "urgent")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_a_reason_is_required(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_signoff.override, [PART], " ")

    def test_an_admin_releases_a_batch_without_the_sign_offs(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.override, [PART, PART2], "Customer deadline")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.status, record.pending), (record_model.STATUS_RELEASED, {}))
            released = [e for e in record.history if e["event"] == "released"][-1]
            self.assertTrue(released["override"])
            self.assertEqual(record.approvals[-1]["override"]["reason"], "Customer deadline")
            self.assertEqual(len(record.approvals[-1]["override"]["missing"]), 2)

    def test_an_admin_can_act_with_no_request_at_all(self):
        self.set_template()
        self.do("Alex", workflow_signoff.override, [PART], "Urgent", action=workflow_templates.RELEASE)
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_an_override_can_void_with_its_reason(self):
        self.set_template(workflow_templates.VOID, rows=((MANAGER,),))
        self.do("Alex", workflow_signoff.override, [PART], "Duplicate part", action=workflow_templates.VOID)
        self.assertEqual(self.record().status, record_model.STATUS_VOID)


if __name__ == "__main__":
    unittest.main()
