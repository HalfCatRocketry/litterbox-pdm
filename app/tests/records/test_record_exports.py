"""Tests for the STEP and PDF a record keeps (records/record_exports.py): the flag a release sets, clearing it, and
reading and writing the record."""

import unittest

from litterbox.core.part_number import PN
from litterbox.records import record_exports
from litterbox.records import record_lifecycle
from litterbox.records import record_model

BOTH = [record_exports.STEP, record_exports.PDF]


def record(status="in_work", revision="A"):
    return record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "2026-10-21T10:00:00Z", status=status,
                               revision=revision)


def made(*kinds):
    return {kind: {"file": f"cad/HCR-00001-001_A.{record_exports.LABEL[kind]}", "from": {"cad/x": "1" * 64},
                   "solidworks": "32.5.0"} for kind in kinds}


class Flag(unittest.TestCase):
    def test_a_release_asks_for_both_files(self):
        r = record()
        record_lifecycle.mark_released(r, "Alex", ["cad/HCR-00001-001_A.SLDPRT"])
        self.assertTrue(record_exports.is_flagged(r))
        self.assertEqual(record_exports.needed(r, BOTH), BOTH)
        self.assertEqual(record_exports.needed(r, [record_exports.STEP]), [record_exports.STEP])    # no drawing

    def test_a_release_drops_files_made_before_it(self):
        r = record()
        record_exports.record_made(r, "Alex", "A", made(*BOTH), BOTH)
        record_lifecycle.mark_released(r, "Alex", [])
        self.assertEqual(r.exports["A"], {"wanted": True})

    def test_parts_released_before_this_version_are_not_flagged(self):
        r = record(status="released")
        r.released_revision = "A"
        self.assertFalse(record_exports.is_flagged(r))
        self.assertEqual(record_exports.needed(r, BOTH), [])

    def test_an_in_work_part_is_never_flagged(self):
        r = record()
        r.exports["A"] = {"wanted": True}
        self.assertFalse(record_exports.is_flagged(r))


class Making(unittest.TestCase):
    def setUp(self):
        self.r = record()
        record_lifecycle.mark_released(self.r, "Alex", [])

    def test_the_flag_goes_once_every_possible_kind_is_made(self):
        record_exports.record_made(self.r, "Bea", "A", made(record_exports.STEP), BOTH)
        self.assertEqual(record_exports.needed(self.r, BOTH), [record_exports.PDF])
        entry = record_exports.record_made(self.r, "Bea", "A", made(record_exports.PDF), BOTH)
        self.assertFalse(record_exports.is_flagged(self.r))
        self.assertEqual(entry["event"], "files_made")
        self.assertEqual(entry["files"], ["cad/HCR-00001-001_A.PDF"])
        self.assertEqual(self.r.exports["A"]["pdf"]["by"], "Bea")
        self.assertEqual(self.r.exports["A"]["pdf"]["solidworks"], "32.5.0")

    def test_a_part_without_a_drawing_is_done_with_its_step(self):
        record_exports.record_made(self.r, "Bea", "A", made(record_exports.STEP), [record_exports.STEP])
        self.assertFalse(record_exports.is_flagged(self.r))

    def test_an_admin_making_them_again_is_recorded(self):
        entry = record_exports.record_made(self.r, "Admin", "A", made(*BOTH), BOTH, forced=True)
        self.assertTrue(entry["forced"])

    def test_the_record_is_written_and_read_back(self):
        record_exports.record_made(self.r, "Bea", "A", made(*BOTH), BOTH)
        again = record_model.Record.from_dict(self.r.to_dict())
        self.assertEqual(again.exports, self.r.exports)
        self.assertNotIn("exports", record_model.Record.from_dict(record().to_dict()).to_dict())

    def test_a_damaged_exports_section_is_refused(self):
        data = self.r.to_dict()
        for bad in (["A"], {"A": "made"}, {"not a revision": {}}):
            data["exports"] = bad
            with self.assertRaises(record_model.RegistryError):
                record_model.Record.from_dict(data)


if __name__ == "__main__":
    unittest.main()
