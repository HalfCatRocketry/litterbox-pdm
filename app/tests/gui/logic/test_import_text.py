"""Tests for the Import window's texts in gui/logic/import_table.py."""

import unittest
from types import SimpleNamespace

from litterbox.gui.logic import import_table


def item(name, pn):
    return SimpleNamespace(main_path=f"C:/old cad/{name}", already_imported_as=pn)


class AlreadyImportedQuestion(unittest.TestCase):
    def test_names_each_file_and_its_part_number(self):
        text = import_table.already_imported_question([item("valve.SLDPRT", "HCR-00005-001")], 3)
        self.assertIn("1 of the 3 parts found may already have been imported", text)
        self.assertIn("valve.SLDPRT  (imported as HCR-00005-001)", text)
        self.assertIn("new parts with new part numbers", text)
        self.assertIn("Cancel to stop", text)

    def test_says_all_and_shortens_a_long_list(self):
        items = [item(f"p{n}.SLDPRT", f"HCR-0000{n}-001") for n in range(10)]
        text = import_table.already_imported_question(items, 10)
        self.assertIn("All parts found", text)
        self.assertIn("...and 2 more", text)
        self.assertNotIn("p9.SLDPRT", text)


if __name__ == "__main__":
    unittest.main()
