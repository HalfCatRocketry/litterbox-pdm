"""Tests for records/record_changes.py: which parts take form, fit, function and a disposition, checking them, and
reading them back from a record's history."""

import unittest
from litterbox.core.doc_number import DocNumber
from litterbox.core.part_number import PN
from litterbox.records import record_changes
from litterbox.records import record_model

P = PN("HCR", 1, 1)
AT = "2026-10-11T09:30:00Z"


class TestWanted(unittest.TestCase):
    def test_a_first_release_takes_nothing_and_rev_b_takes_both(self):
        self.assertEqual(record_changes.wanted(P, "release", "A", ""), (False, False))
        self.assertEqual(record_changes.wanted(P, "release", "B", "A"), (True, True))
        self.assertEqual(record_changes.wanted(P, "release", "B", ""), (True, False))    # nothing released before

    def test_a_void_takes_a_disposition_and_other_actions_nothing(self):
        self.assertEqual(record_changes.wanted(P, "void", "A", ""), (False, True))
        for action in ("reopen", "make_cots", "remove_document"):
            self.assertEqual(record_changes.wanted(P, action, "B", "A"), (False, False))

    def test_documents_take_nothing(self):
        self.assertEqual(record_changes.wanted(DocNumber("PROP", 1), "release", "B", "A"), (False, False))

    def test_the_earlier_revision(self):
        self.assertEqual(record_changes.earlier_revision("B", "A"), "A")
        self.assertEqual(record_changes.earlier_revision("A", "A"), "")
        self.assertEqual(record_changes.earlier_revision("A", ""), "")


class TestClean(unittest.TestCase):
    def test_keeps_what_is_asked_in_order(self):
        self.assertEqual(record_changes.clean({"changed": ["function", "form"], "disposition": "scrap"}, True, True),
                         {"changed": ["form", "function"], "disposition": "scrap"})
        self.assertEqual(record_changes.clean({"changed": ["form"], "disposition": "scrap"}, False, True),
                         {"disposition": "scrap"})
        self.assertEqual(record_changes.clean(None, True, False), {"changed": []})

    def test_a_disposition_asked_for_is_required_and_must_be_known(self):
        for bad in ({}, {"disposition": "burn"}):
            with self.assertRaises(record_changes.ChangeError) as ctx:
                record_changes.clean(bad, True, True, where="HCR-00001-001: ")
            self.assertIn("HCR-00001-001: Choose a disposition", str(ctx.exception))
        with self.assertRaises(record_changes.ChangeError):
            record_changes.clean({"changed": ["colour"]}, True, False)

    def test_changes_text(self):
        self.assertEqual(record_changes.changes_text(["fit", "form"]), "Form, Fit")
        self.assertEqual(record_changes.changes_text([]), "None")


class TestReadingBack(unittest.TestCase):
    def test_the_disposition_and_what_changed_come_from_the_history(self):
        record = record_model.Record(P, "Bracket", "Alex", AT, revision="B", released_revision="A")
        record.history = [{"event": "released", "by": "Alex", "at": AT, "revision": "A"}]
        self.assertIsNone(record_changes.changed_in(record, "A"))
        record.history.append({"event": "released", "by": "Alex", "at": AT, "revision": "B", "changed": ["fit"]})
        record_changes.record_disposition(record, "Alex", "rework", "A", "Rev B released")
        self.assertEqual(record_changes.changed_in(record, "B"), ["fit"])
        self.assertEqual(record_changes.disposition_of(record, "A"), "rework")
        self.assertEqual(record_changes.disposition_event(record, "A")["reason"], "Rev B released")
        self.assertEqual(record_changes.disposition_of(record, "B"), "")


if __name__ == "__main__":
    unittest.main()
