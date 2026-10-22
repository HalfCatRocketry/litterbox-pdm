"""Tests for a document's own Details window in words: a revision's details, its files, and the part revisions that
link to it."""

import unittest
from types import SimpleNamespace

from litterbox.core.doc_number import DocNumber
from litterbox.core.part_number import PN
from litterbox.documents import doc_types
from litterbox.gui.logic import document_details_text
from litterbox.records import record_model

TYPES = doc_types.by_key([doc_types.DocType("prop", "Propulsion Document", "PROP")])
FILES = {"A": ["documents/PROP-0001_A.pdf", "documents/PROP-0001_A.docx"], "B": ["documents/PROP-0001_B.docx"]}


def document():
    record = record_model.Record(DocNumber("PROP", 1), "Igniter test", "Alex", "2026-10-01T10:00:00Z",
                                 revision="B", released_revision="A", doc_type="prop", description="Hot fire")
    record.history.append({"event": record_model.EVENT_RELEASED, "revision": "A", "by": "Bea",
                           "at": "2026-10-02T10:00:00Z"})
    return record


class Details(unittest.TestCase):
    def test_a_revision_is_described_as_a_document_not_a_part(self):
        fields = dict(document_details_text.revision_details(document(), "A", FILES, TYPES, local=False))
        self.assertEqual(fields["Document"], "PROP-0001")
        self.assertEqual(fields["Type"], "Propulsion Document")
        self.assertEqual(fields["Revision"], "Rev A")
        self.assertEqual(fields["State"], "Released")
        self.assertIn("by Bea", fields["Released"])
        self.assertNotIn("Part", fields)
        self.assertNotIn("STEP/PDF", fields)

    def test_the_working_revision_and_an_unknown_type(self):
        record = document()
        record.doc_type = "gone"
        fields = dict(document_details_text.revision_details(record, "B", FILES, TYPES, local=False))
        self.assertEqual(fields["Revision"], "Rev B (working)")
        self.assertEqual(fields["Type"], "gone")
        self.assertNotIn("Released", fields)

    def test_files_of_one_revision(self):
        self.assertEqual(document_details_text.file_rows(FILES, "A"),
                         [("documents/PROP-0001_A.docx", ("PROP-0001_A.docx", "DOCX")),
                          ("documents/PROP-0001_A.pdf", ("PROP-0001_A.pdf", "PDF"))])
        self.assertEqual(document_details_text.file_rows(FILES, "C"), [])


class WhereLinked(unittest.TestCase):
    def test_rows_say_how_each_linking_revision_stands(self):
        one, two, gone = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 9, 1)
        rows = {one: SimpleNamespace(name="Igniter", revision="B", state="Checked out by you",
                                     released_revisions=("A",)),
                two: SimpleNamespace(name="Nozzle", revision="A", state="Released", released_revisions=("A",))}
        links = [(one, "A"), (one, "B"), (two, "A"), (gone, "A")]
        found = document_details_text.linked_rows(links, rows)
        self.assertEqual([values for _iid, values in found], [
            ("HCR-00001-001", "Igniter", "A", "Released (superseded)"),
            ("HCR-00001-001", "Igniter", "B", "Checked out by you"),
            ("HCR-00002-001", "Nozzle", "A", "Released"),
            ("HCR-00009-001", "", "A", "Not in the list: run Get Latest")])
        self.assertEqual(document_details_text.linked_note(links), "Linked from 3 parts (4 revisions)")
        self.assertEqual(document_details_text.linked_note([]), "No part links to this document.")


if __name__ == "__main__":
    unittest.main()
