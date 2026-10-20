"""Tests for how many of each part an assembly uses (a record's `quantities`): saving them, the rules at check-in,
revise and cancel, and when a BOM needs updating."""

import unittest
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.records.record_model import RegistryError
from tests.support.registry_case import RegistryTestCase

ASM_FILES = ["cad/HCR-00002-001_A.SLDASM"]
BOLT, PLATE = "HCR-00004-001_A", "HCR-00005-001_B"


class SavingThem(RegistryTestCase):
    def test_they_survive_saving_and_loading(self):
        record = self.make(2)
        record.references = {"A": [BOLT, PLATE]}
        record.quantities = {"A": {PLATE: 1, BOLT: 6}}
        record_store.save(self.repo, record)
        self.assertEqual(record_store.load(self.repo, record.pn).quantities, {"A": {BOLT: 6, PLATE: 1}})
        self.assertIn("quantities:", (self.repo / "PN-logs" / "HCR-00002-001.yaml").read_text())

    def test_a_record_without_them_writes_no_field(self):
        record = self.make(2)
        self.assertNotIn("quantities", record_model.dump(record))
        self.assertEqual(record_store.load(self.repo, record.pn).quantities, {})

    def test_bad_counts_are_refused(self):
        data = record_model.Record(pn=self.make(2).pn, name="x", created_by="Alex", created_at="t").to_dict()
        for bad in ({"A": {BOLT: -1}}, {"A": {BOLT: "four"}}, {"A": {BOLT: True}}, {"A": [BOLT]}, ["A"],
                    {"?": {BOLT: 1}}):
            with self.subTest(bad=bad), self.assertRaises(RegistryError):
                record_model.Record.from_dict(dict(data, quantities=bad))


class AtCheckIn(RegistryTestCase):
    def assembly(self):
        record = self.make(2)
        record_lifecycle.record_checkout(record, "Alex", ASM_FILES)
        return record

    def test_counts_are_stored_and_every_part_used_gets_one(self):
        record = self.assembly()
        event = record_lifecycle.record_checkin(record, "Alex", ASM_FILES, "x", references=[BOLT, PLATE],
                                                quantities={BOLT: 6})
        self.assertEqual(record.quantities, {"A": {BOLT: 6, PLATE: 0}})
        self.assertEqual(event["quantities"], {BOLT: 6, PLATE: 0})
        self.assertFalse(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))

    def test_an_assembly_checked_in_without_counts_loses_its_old_ones(self):
        record = self.assembly()
        record_lifecycle.record_checkin(record, "Alex", ASM_FILES, references=[BOLT], quantities={BOLT: 6})
        record_lifecycle.record_checkout(record, "Alex", ASM_FILES)
        event = record_lifecycle.record_checkin(record, "Alex", ASM_FILES, references=[BOLT])
        self.assertEqual(record.quantities, {})
        self.assertNotIn("quantities", event)
        self.assertTrue(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))
        self.assertFalse(record_lifecycle.references_need_update(record, "A", ASM_FILES))

    def test_a_check_in_with_no_assembly_file_keeps_them(self):
        record = self.assembly()
        record.references, record.quantities = {"A": [BOLT]}, {"A": {BOLT: 6}}
        record_lifecycle.record_checkin(record, "Alex", ["cad/HCR-00002-001_A.SLDDRW"])
        self.assertEqual(record.quantities, {"A": {BOLT: 6}})


class NeedsUpdate(RegistryTestCase):
    def test_when_a_bom_needs_updating(self):
        record = self.make(2)
        record.references = {"A": [BOLT, PLATE]}
        self.assertTrue(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))         # never counted
        record.quantities = {"A": {BOLT: 6}}
        self.assertTrue(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))         # an older check-in
        record.quantities = {"A": {BOLT: 6, PLATE: 1}}
        self.assertFalse(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))
        record.references_outdated = ["A"]
        self.assertTrue(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))
        self.assertFalse(record_lifecycle.bom_needs_update(record, "A", ["cad/HCR-00002-001_A.SLDPRT"]))
        record.cots = True
        self.assertFalse(record_lifecycle.bom_needs_update(record, "A", ASM_FILES))


class ReviseAndCancel(RegistryTestCase):
    def test_revise_copies_the_counts_and_cancel_drops_them(self):
        record = self.make(2)
        record.references, record.quantities = {"A": [BOLT]}, {"A": {BOLT: 6}}
        record_lifecycle.mark_released(record, "Alex", ASM_FILES)
        record_revisions.mark_revised(record, "Alex", "Bigger", [])
        self.assertEqual(record.quantities, {"A": {BOLT: 6}, "B": {BOLT: 6}})
        record_revisions.mark_revision_cancelled(record, "Alex", "No", [])
        self.assertEqual(record.quantities, {"A": {BOLT: 6}})


if __name__ == "__main__":
    unittest.main()
