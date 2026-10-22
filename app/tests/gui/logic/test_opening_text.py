"""Tests for what Open PDF offers: every revision with a PDF, newest first, and what to say when there is none."""

import unittest

from litterbox.core.part_number import PN
from litterbox.gui.logic import opening_text
from litterbox.parts.part_status import PartStatus

PN7 = PN("HCR", 7, 1)


def row(revisions):
    return PartStatus(PN7, "Part", "in_work", "Available", "ok", revision="C", released_revision="B",
                      revisions=revisions)


class OpenPdf(unittest.TestCase):
    def test_every_revision_with_a_pdf_newest_first(self):
        found = opening_text.pdf_choices(row({
            "A": ["cad/HCR-00007-001_A.SLDPRT", "cad/HCR-00007-001_A.PDF"],
            "B": ["cad/HCR-00007-001_B.SLDPRT", "cad/HCR-00007-001_B.SLDDRW", "cad/HCR-00007-001_B.pdf"],
            "C": ["cad/HCR-00007-001_C.SLDPRT", "cad/HCR-00007-001_C.SLDDRW"]}))
        self.assertEqual([rev for rev, _files in found], ["B", "A"])
        self.assertEqual(opening_text.pdf_message(row({"B": ["cad/HCR-00007-001_B.pdf"]})), "")

    def test_no_pdf_says_how_to_make_one_when_there_is_a_drawing(self):
        with_drawing = row({"C": ["cad/HCR-00007-001_C.SLDPRT", "cad/HCR-00007-001_C.SLDDRW"]})
        self.assertEqual(opening_text.pdf_choices(with_drawing), [])
        self.assertIn("Generate STEP/PDF", opening_text.pdf_message(with_drawing))
        self.assertIn("no drawing", opening_text.pdf_message(row({"C": ["cad/HCR-00007-001_C.SLDPRT"]})))


if __name__ == "__main__":
    unittest.main()
