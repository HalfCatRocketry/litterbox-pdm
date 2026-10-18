"""Tests for how references are stored in a record. They need Linux, macOS or WSL."""

import unittest
from litterbox.records import record_model
from litterbox.core.part_number import PN


class TestRecordFormat(unittest.TestCase):
    def test_round_trip_and_validation(self):
        record = record_model.Record(pn=PN("HCR", 2, 1), name="x", created_by="a", created_at="t")
        record.references = {"B": ["HCR-00001-001_A"], "A": ["HCR-00001-001_A", "HCR-00003-001_C"]}
        again = record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(record)))
        self.assertEqual(again.references, record.references)
        data = record.to_dict()
        self.assertEqual(list(data["references"]), ["A", "B"])
        record.references_outdated = ["B", "A"]
        self.assertEqual(record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(record))).references_outdated,
                         ["A", "B"])
        data["references"] = ["nope"]
        with self.assertRaises(record_model.RegistryError):
            record_model.Record.from_dict(data)
        self.assertNotIn("references", record_model.Record(pn=PN("HCR", 3, 1), name="y", created_by="a",
                                                       created_at="t").to_dict())


if __name__ == "__main__":
    unittest.main()
