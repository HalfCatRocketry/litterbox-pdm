"""Tests for records/record_lifecycle.py: the status rules and pending requests."""

import unittest
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.records.record_model import RegistryError
from tests.support.registry_case import TIMESTAMP, RegistryTestCase


class TestStatusChanges(RegistryTestCase):
    FILES = ["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW"]

    def test_full_lifecycle(self):
        record = self.make(1)
        record_lifecycle.record_checkout(record, "Alex", self.FILES)
        record_lifecycle.record_checkin(record, "Alex", self.FILES, "Added fillet")
        record_lifecycle.mark_released(record, "Jo", self.FILES)
        self.assertEqual(record.status, "released")
        record_lifecycle.mark_reopened(record, "Jo", "Bore diameter wrong")
        self.assertEqual(record.status, "in_work")
        self.assertEqual([e["event"] for e in record.history],
                         ["created", "checked_out", "checked_in", "released", "reopened"])
        record_store.save(self.repo, record)
        self.assertEqual(record_store.load(self.repo, record.pn), record)
        for event in record.history:
            self.assertRegex(event["at"], TIMESTAMP)

    def test_event_details(self):
        record = self.make(1)
        record_lifecycle.record_checkin(record, "Alex", self.FILES, "  Added fillet ")
        self.assertEqual(record.history[-1]["comment"], "Added fillet")
        record_lifecycle.record_checkin(record, "Alex", self.FILES)
        self.assertNotIn("comment", record.history[-1])

    def test_released_part_cannot_be_checked_out(self):
        record = self.make(1)
        record_lifecycle.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            record_lifecycle.record_checkout(record, "Alex", self.FILES)

    def test_cannot_release_twice_or_reopen_unreleased(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_reopened(record, "Jo", "reason")
        record_lifecycle.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_released(record, "Jo", self.FILES)

    def test_reopen_and_void_need_a_reason(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_void(record, "Jo", "  ")
        self.assertEqual(record.status, "in_work")
        record_lifecycle.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_reopened(record, "Jo", "")
        self.assertEqual(record.status, "released")

    def test_void_rules(self):
        record = self.make(1)
        record_lifecycle.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):          # must reopen first
            record_lifecycle.mark_void(record, "Jo", "scrapped")
        record_lifecycle.mark_reopened(record, "Jo", "changed my mind")
        record_lifecycle.mark_void(record, "Jo", "scrapped")
        self.assertEqual(record.status, "void")
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_reopened(record, "Jo", "oops")

    def test_events_need_a_user(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            record_lifecycle.add_event(record, "checked_in", "  ")


class TestPendingRequests(RegistryTestCase):
    PENDING = {"id": "ab12cd34", "action": "release", "revision": "A", "requested_by": "Alex",
               "requested_at": "2026-10-11T00:00:00Z", "template_name": "T1",
               "template": {"allow_same_person": False, "requester_may_sign": True,
                            "signoffs": [{"roles": ["Quality"]}]},
               "slots": [{"roles": ["Quality"], "id": "bea", "name": "Bea"}],
               "files": {"cad/x.SLDPRT": "abc"}, "signoffs": []}

    def pending(self, base=7):
        record = self.make(base)
        record.pending = dict(self.PENDING)
        record_store.save(self.repo, record)
        return record_store.load(self.repo, record.pn)

    def test_a_pending_request_survives_saving_and_loading(self):
        loaded = self.pending()
        self.assertEqual(loaded.pending, self.PENDING)

    def test_a_record_without_one_writes_no_pending_field(self):
        record = self.make(8)
        self.assertNotIn("pending", record.to_dict())
        self.assertEqual(record.pending, {})

    def test_pending_parts_cannot_be_checked_out_voided_cots_or_have_their_revision_cancelled(self):
        record = self.pending()
        for action in (lambda: record_lifecycle.record_checkout(record, "Jo", []), lambda: record_lifecycle.mark_void(record, "Jo", "x"),
                       lambda: record_lifecycle.mark_cots(record, "Jo", []),
                       lambda: record_lifecycle.mark_reopened(record, "Jo", "x"),
                       lambda: record_revisions.mark_revision_cancelled(record, "Jo", "x", [])):
            with self.assertRaises(RegistryError) as ctx:
                action()
            self.assertIn("waiting for sign-offs", str(ctx.exception))

    def test_a_malformed_request_is_refused(self):
        record = self.make(9)
        for bad in ("text", {"action": "release"}, {**self.PENDING, "signoffs": "none"},
                    {**self.PENDING, "template": []},
                    {**self.PENDING, "slots": "none"}, {k: v for k, v in self.PENDING.items() if k != "slots"}):
            data = record.to_dict()
            data["pending"] = bad
            with self.assertRaises(RegistryError):
                record_model.Record.from_dict(data)

    def test_unquoted_timestamps_in_a_hand_edited_request_become_text(self):
        import datetime
        data = self.make(10).to_dict()
        data["pending"] = {**self.PENDING, "requested_at": datetime.datetime(2026, 10, 11, 0, 0, 0),
                           "signoffs": [{"by": "Bea", "slot": 0, "at": datetime.datetime(2026, 10, 11, 1, 0, 0)}]}
        loaded = record_model.Record.from_dict(data)
        self.assertEqual(loaded.pending["requested_at"], "2026-10-11T00:00:00Z")
        self.assertEqual(loaded.pending["signoffs"][0]["at"], "2026-10-11T01:00:00Z")

    def test_a_pending_part_cannot_be_revised(self):
        record = self.pending()
        record.status = record_model.STATUS_RELEASED
        self.assertIn("waiting for sign-offs", record_revisions.can_revise(record))

    def test_release_details_go_on_the_event(self):
        record = self.make(11)
        event = record_lifecycle.mark_released(record, "Jo", ["cad/x.SLDPRT"], signoffs=["Bea"], override=None)
        self.assertEqual(event["signoffs"], ["Bea"])
        self.assertNotIn("override", event)


if __name__ == "__main__":
    unittest.main()
