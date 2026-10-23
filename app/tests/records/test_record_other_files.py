"""Tests for records/record_other_files.py: the files each assembly revision uses that aren't Litterbox parts, as its
record keeps them, and how check-in, Revise and Cancel Revision treat them."""

import unittest

from litterbox.core.part_number import PN
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_other_files as other
from litterbox.records import record_revisions
from litterbox.records.record_model import RegistryError
from tests.support.registry_case import RegistryTestCase

SCREW = {"file": "C:\\SOLIDWORKS Data\\browser\\screw.sldprt", "toolbox": True}
NUT = {"file": "toolbox/browser/nut.sldprt", "toolbox": True}
ASM_FILES = ["cad/HCR-00042-500_A.SLDASM"]


class Keeping(RegistryTestCase):
    def test_written_and_read_back_in_order(self):
        record = self.make(42)
        other.set_other_files(record, [SCREW, NUT])
        data = record.to_dict()
        self.assertEqual([e["file"] for e in data["other_files"]["A"]], [SCREW["file"], NUT["file"]])
        again = record_model.Record.from_dict(data)
        self.assertEqual(other.entries(again, "A"), [SCREW, NUT])
        self.assertTrue(other.is_read(again, "A"))

    def test_read_with_nothing_is_different_from_not_read(self):
        record = self.make(42)
        self.assertFalse(other.is_read(record))
        self.assertTrue(other.set_other_files(record, []))                    # read, and it uses nothing else
        self.assertTrue(other.is_read(record))
        self.assertFalse(other.set_other_files(record, []))
        self.assertNotIn("other_files", record_model.Record(PN("HCR", 1, 1), "x", "Alex", "t").to_dict())

    def test_a_bad_section_is_refused(self):
        data = self.make(42).to_dict()
        for bad in ([1], {"A": "x"}, {"A": [{"toolbox": True}]}, {"A1": []}):
            data["other_files"] = bad
            with self.assertRaises(RegistryError):
                record_model.Record.from_dict(data)


class CheckInReviseCancel(RegistryTestCase):
    def test_check_in_keeps_what_was_read_and_forgets_it_when_not_read(self):
        record = self.make(42, variant=500)
        record_lifecycle.record_checkin(record, "Alex", ASM_FILES, references=[], other_files=[SCREW])
        self.assertEqual(other.entries(record), [SCREW])
        record_lifecycle.record_checkin(record, "Alex", ASM_FILES)              # without SolidWorks
        self.assertFalse(other.is_read(record))
        record_lifecycle.record_checkin(record, "Alex", ["cad/HCR-00042-500_A.SLDDRW"], other_files=None)
        self.assertFalse(other.is_read(record))

    def test_revise_carries_them_on_and_cancelling_drops_them(self):
        record = self.make(42, variant=500)
        other.set_other_files(record, [NUT])
        record_lifecycle.mark_released(record, "Alex", ASM_FILES)
        record_revisions.mark_revised(record, "Alex", "Longer screws", [])
        self.assertEqual(other.entries(record, "B"), [NUT])
        record_revisions.mark_revision_cancelled(record, "Alex", "Not needed", [])
        self.assertFalse(other.is_read(record, "B"))
        self.assertEqual(other.entries(record, "A"), [NUT])


if __name__ == "__main__":
    unittest.main()
