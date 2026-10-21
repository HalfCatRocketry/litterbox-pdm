"""Tests for the window's side of documents: the Documents screen's table, the files offered, a part's Documents
tab, and when links may change."""

import unittest
from types import SimpleNamespace

from litterbox.core.doc_number import DocNumber
from litterbox.documents import doc_types
from litterbox.gui.logic import document_text
from litterbox.gui.logic import request_parts
from litterbox.records import record_model

TYPES = doc_types.by_key([doc_types.DocType("prop", "Propulsion Document", "PROP"),
                          doc_types.DocType("tp", "Test Procedure", "TP", hidden=True)])


def doc(prefix, number, title, kind="ok", files=(), released="", doc_type="prop", revision="A"):
    return SimpleNamespace(pn=DocNumber(prefix, number), name=title, description="", doc_type=doc_type, kind=kind,
                           state=kind, files=list(files), revision=revision, released_revision=released,
                           revisions={revision: list(files)}, record_status="in_work")


ROWS = [doc("PROP", 1, "Igniter test", files=["documents/PROP-0001_A.docx", "documents/PROP-0001_A.pdf"]),
        doc("PROP", 2, "Nozzle plan", kind="released", released="A"),
        doc("TP", 1, "Hot fire", doc_type="tp", kind="void")]


class Screen(unittest.TestCase):
    def test_the_table_is_searched_and_filtered_by_type_newest_first(self):
        table = document_text.table(ROWS, TYPES)
        self.assertEqual([iid for iid, _v in table], ["PROP-0002", "PROP-0001", "TP-0001"])
        self.assertEqual(table[1][1], ("PROP-0001", "Igniter test", "Propulsion Document", "A", "DOCX, PDF", "ok"))
        self.assertEqual([iid for iid, _v in document_text.table(ROWS, TYPES, "nozzle")], ["PROP-0002"])
        self.assertEqual([iid for iid, _v in document_text.table(ROWS, TYPES, "", "Test Procedure")], ["TP-0001"])

    def test_a_hidden_type_is_still_a_filter_while_documents_use_it(self):
        self.assertEqual(document_text.type_filters(list(TYPES.values()), ROWS),
                         [document_text.ALL_TYPES, "Propulsion Document", "Test Procedure"])
        self.assertEqual(document_text.type_filters(list(TYPES.values()), ROWS[:2]),
                         [document_text.ALL_TYPES, "Propulsion Document"])
        self.assertEqual(document_text.type_name("gone", TYPES), "gone")

    def test_files_offered(self):
        self.assertEqual([label for label, _rel in document_text.file_choices(ROWS[0])],
                         ["PROP-0001_A.docx", "PROP-0001_A.pdf"])
        self.assertEqual(document_text.file_choices(ROWS[0], "B"), [])


class PartTab(unittest.TestCase):
    def test_a_revision_lists_its_documents(self):
        record = record_model.Record(object(), "Bracket", "Alex", "t", documents={"A": ["PROP-0002", "PROP-0009"]})
        rows = document_text.link_rows(record, "A", {str(r.pn): r for r in ROWS}, TYPES)
        self.assertEqual(rows[0], ("PROP-0002", ("PROP-0002", "Nozzle plan", "Propulsion Document", "A", "Released")))
        self.assertIn("Not found", rows[1][1][-1])
        self.assertEqual(document_text.link_rows(record, "B", {}, TYPES), [])

    def test_links_never_go_to_void_or_already_linked_documents(self):
        self.assertEqual([str(r.pn) for r in document_text.linkable(ROWS, ["PROP-0001"])], ["PROP-0002"])

    def test_when_links_may_change(self):
        part = SimpleNamespace(kind="mine", revision="B", record_status="in_work")
        self.assertEqual(document_text.link_mode(part, "B", False), ("checkout", ""))
        self.assertIn("working revision", document_text.link_mode(part, "A", True)[1])
        part = SimpleNamespace(kind="released", revision="A", record_status="released")
        self.assertEqual(document_text.link_mode(part, "A", True), ("released", ""))
        self.assertIn("Admin or a superuser", document_text.link_mode(part, "A", False)[1])
        part = SimpleNamespace(kind="ok", revision="A", record_status="in_work")
        self.assertIn("Check the part out", document_text.link_mode(part, "A", True)[1])

    def test_a_document_workflow_offers_only_documents(self):
        parts = [SimpleNamespace(pn=object(), kind="ok")]
        offered = request_parts.addable_rows("release_document", ROWS + parts)
        self.assertEqual([str(r.pn) for r in offered], ["PROP-0001"])
        self.assertEqual(request_parts.addable_rows("remove_document", ROWS), [])


if __name__ == "__main__":
    unittest.main()
