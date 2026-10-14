"""Tests for gui/logic/checkin_text.py and error_text.py: check-in and error messages."""

import unittest
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import error_text
from litterbox.parts.part_changes import ChangeReport
from litterbox.core.part_number import PN


class TestUnchangedParts(unittest.TestCase):
    @staticmethod
    def report(has_changes, unchanged=()):
        return ChangeReport(has_changes, [], list(unchanged), False, False)

    def test_only_parts_without_changes_are_listed(self):
        a, b, c = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)
        reports = [
            (a, self.report(False, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"])),
            (b, self.report(True, ["cad/HCR-00002-001_A.SLDDRW"])),      # part changed, drawing didn't: no prompt
            (c, self.report(False)),
        ]
        self.assertEqual(checkin_text.parts_without_changes(reports), [
            (a, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]),
            (c, []),
        ])
        self.assertEqual(checkin_text.parts_without_changes([]), [])

    def test_dialog_lines(self):
        unchanged = [
            (PN("HCR", 1, 1), ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]),
            (PN("HCR", 3, 1), []),
        ]
        self.assertEqual(checkin_text.unchanged_lines(unchanged), [
            "HCR-00001-001", "    HCR-00001-001_A.SLDDRW", "    HCR-00001-001_A.SLDPRT",
            "HCR-00003-001", "    (no CAD files yet)",
        ])


class TestMessages(unittest.TestCase):
    def test_cad_changes_only_lists_cad_files(self):
        paths = ["cad/HCR-00001-001_A.SLDPRT", "PN-logs/HCR-00001-001.yaml", "cad/HCR-00002-001_A.SLDDRW"]
        self.assertEqual(checkin_text.cad_changes(paths), ["HCR-00001-001_A.SLDPRT", "HCR-00002-001_A.SLDDRW"])
        self.assertEqual(checkin_text.cad_changes(["PN-logs/x.yaml"]), [])

    def test_cad_changes_limit(self):
        names = checkin_text.cad_changes([f"cad/HCR-{n:05d}-001.SLDPRT" for n in range(1, 21)], limit=3)
        self.assertEqual(len(names), 4)
        self.assertEqual(names[-1], "... and 17 more")

    def test_shorten(self):
        self.assertEqual(error_text.shorten("  short  "), "short")
        long_text = error_text.shorten("x" * 5000, limit=100)
        self.assertLess(len(long_text), 200)
        self.assertIn("full text is in the log", long_text)


if __name__ == "__main__":
    unittest.main()
