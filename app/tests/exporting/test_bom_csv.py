"""Tests for writing a BOM as a .csv spreadsheet."""

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from litterbox.core.part_number import PN
from litterbox.exporting import bom_csv
from litterbox.exporting import export_folder
from litterbox.references import bom


def line(level, base, name, **fields):
    return bom.BomLine(level, PN("HCR", base, 1), "A", name, status="in_work", **fields)


class BomCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "Litterbox"
        self.root.mkdir()

    def read(self, path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def test_a_heading_row_then_one_row_per_line(self):
        found = [line(1, 2, "Frame", sub_assembly=True),
                 line(2, 4, "Bolt", cots=True, purchasing={"supplier": "Acme", "unit_cost": "0.10",
                                                           "lead_time_days": 3})]
        path = bom_csv.write(self.tmp / "bom", found, self.root)
        self.assertEqual(path.name, "bom.csv")
        table = self.read(path)
        self.assertEqual(table[0], list(bom_csv.COLUMNS))
        self.assertEqual(table[1][:8], ["1", "HCR-00002-001", "A", "Frame", "", "in work", "", "OK"])
        self.assertEqual(table[2][6:], ["Yes", "OK", "Acme", "", "0.10", "3"])

    def test_text_that_looks_like_a_formula_is_never_run(self):
        path = bom_csv.write(self.tmp / "b.csv", [line(1, 2, "=HYPERLINK(\"http://x\")",
                                                       purchasing={"supplier": "+Acme"})], self.root)
        row = self.read(path)[1]
        self.assertEqual(row[3], "'=HYPERLINK(\"http://x\")")
        self.assertEqual(row[8], "'+Acme")
        self.assertEqual(bom_csv.safe_cell("Bolt-M6"), "Bolt-M6")

    def test_an_every_part_once_list_has_no_level(self):
        self.assertEqual(bom_csv.rows([line(0, 2, "Frame")])[1][0], "")

    def test_never_inside_litterbox(self):
        with self.assertRaisesRegex(export_folder.ExportError, "outside"):
            bom_csv.write(self.root / "bom.csv", [], self.root)

    def test_the_name_offered(self):
        self.assertEqual(bom_csv.default_name(PN("HCR", 2, 1), "B", bom.INDENTED), "HCR-00002-001_B BOM (indented).csv")


if __name__ == "__main__":
    unittest.main()
