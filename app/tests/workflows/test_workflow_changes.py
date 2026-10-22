"""Tests for what a release says changed and the disposition of the earlier revision's parts (records/record_changes.py),
through a workflow and without one, and for a void's disposition. Uses the two-user vault (Alex is the Owner and a
Responsible Engineer; Bea is a Member with the Quality role). They need Linux, macOS or WSL (or LITTERBOX_GIT_TESTS=1
on Windows)."""

import unittest
from tests.support.vault_fixture import PART
from litterbox.errors import LitterboxError
from litterbox.parts import lifecycle
from litterbox.records import record_changes
from litterbox.records import record_model
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import ENGINEER, Fixture

RELEASE, VOID = workflow_templates.RELEASE, workflow_templates.VOID


class TestReleaseChanges(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.make_rev_b()

    def test_a_rev_b_request_needs_a_dispo_when_changes_are_given(self):
        self.set_template()
        with self.assertRaises(LitterboxError) as ctx:
            self.request(changes={str(PART): {"changed": ["form"]}})
        self.assertIn("Choose a disposition", str(ctx.exception))
        self.assertEqual(self.record().pending, {})

    def test_the_release_records_what_changed_and_the_earlier_revisions_dispo(self):
        self.set_template()
        self.request(changes={str(PART): {"changed": ["function", "form"], "disposition": "rework"}})
        pending = self.record().pending
        self.assertEqual(pending["change"], {"changed": ["form", "function"], "disposition": "rework"})
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.get_latest("Bea")
        self.do("Bea", workflow_signoff.sign_off, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision), (record_model.STATUS_RELEASED, "B"))
        self.assertEqual(record_changes.changed_in(record, "B"), ["form", "function"])
        self.assertEqual(record_changes.disposition_of(record, "A"), "rework")
        self.assertEqual(record_changes.disposition_event(record, "A")["reason"], "Rev B released")
        self.assertEqual(record_changes.disposition_of(record, "B"), "")

    def test_without_a_workflow_the_release_takes_them_too(self):
        with self.user("Alex"):
            done, failed = lifecycle.release_many(self.a, [PART], changes={str(PART): {"changed": [],
                                                                                      "disposition": "scrap"}})
        self.assertEqual((len(done), failed), (1, []))
        record = self.record()
        self.assertEqual(record_changes.changed_in(record, "B"), [])
        self.assertEqual(record_changes.disposition_of(record, "A"), "scrap")

    def test_without_a_workflow_a_missing_dispo_stops_that_part(self):
        with self.user("Alex"):
            done, failed = lifecycle.release_many(self.a, [PART], changes={})
        self.assertEqual(done, [])
        self.assertIn("Choose a disposition", str(failed[0][1]))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)


class TestVoidDisposition(Fixture, unittest.TestCase):
    def test_a_void_records_the_dispo_of_the_voided_revision(self):
        self.set_template(VOID, rows=((ENGINEER,),))
        self.do("Alex", workflow_request.request, [PART], VOID, "T", ["alex"], reason="Not needed",
                changes={str(PART): {"disposition": "return_to_supplier"}})
        self.do("Alex", workflow_signoff.sign_off, [PART])
        record = self.record()
        self.assertEqual(record.status, record_model.STATUS_VOID)
        event = record_changes.disposition_event(record, "A")
        self.assertEqual((event["disposition"], event["reason"]), ("return_to_supplier", "voided"))


if __name__ == "__main__":
    unittest.main()
