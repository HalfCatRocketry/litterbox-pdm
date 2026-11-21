"""Tests for gui/logic/download_text.py: what Repair Files asks and reports."""

import unittest

from litterbox.gui.logic import download_text
from litterbox.parts.file_repair import RepairResult


class RepairText(unittest.TestCase):
    def test_the_question_names_the_files_and_warns(self):
        text = download_text.repair_question(["cad/A.SLDPRT"])
        self.assertIn("1 file on this computer doesn't match", text)
        self.assertIn("  cad/A.SLDPRT", text)
        self.assertIn("changes in these files are lost", text)
        many = download_text.repair_question([f"cad/{n}.SLDPRT" for n in range(20)])
        self.assertIn("20 files on this computer don't match", many)
        self.assertIn("...and 8 more", many)

    def test_the_summary(self):
        title, text, problem = download_text.repair_summary(RepairResult(repaired=["a", "b"]))
        self.assertEqual((title, problem), ("Repair Files", False))
        self.assertIn("Repaired 2 files", text)
        _t, text, problem = download_text.repair_summary(
            RepairResult(repaired=["a"], failed={"b": "unable to unlink"}, not_downloaded=["c"]))
        self.assertTrue(problem)
        self.assertIn("b: unable to unlink", text)
        self.assertIn("not downloaded", text)
        self.assertIn("checked out now", download_text.repair_summary(RepairResult())[1])


if __name__ == "__main__":
    unittest.main()
