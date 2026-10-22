"""Tests for documents: numbers and types (no git), and their whole life in a vault (types, New Document, files,
check out and in, release, revise, links to parts, and their own workflows), against real git repos with a fake
git-lfs, so those need Linux, macOS or WSL and are skipped on Windows."""

import tempfile
import unittest
from pathlib import Path

from litterbox.core import doc_number
from litterbox.core.doc_number import DocNumber
from litterbox.core.part_number import PNError
from litterbox.documents import doc_create
from litterbox.documents import doc_files
from litterbox.documents import doc_links
from litterbox.documents import doc_types
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import part_status
from litterbox.parts import revise
from litterbox.parts import undoing
from litterbox.records import record_links
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_templates
from tests.support.create_fixture import CreateFixture
from tests.support.vault_fixture import PART, SKIP_ON_WINDOWS
from tests.support.workflow_fixture import CHIEF, Fixture

PROP1 = DocNumber("PROP", 1)


class Numbers(unittest.TestCase):
    def test_numbers_and_file_names(self):
        self.assertEqual(str(PROP1), "PROP-0001")
        self.assertEqual(str(DocNumber("PROP", 12345)), "PROP-12345")
        self.assertEqual(doc_number.parse("prop-0001"), PROP1)
        self.assertIsNone(doc_number.try_parse("HCR-00001-001"))
        self.assertEqual(doc_number.parse_filename("documents/PROP-0001_A.docx"), (PROP1, "A", "DOCX"))
        self.assertEqual(doc_number.filename(PROP1, "b", ".docx"), "PROP-0001_B.docx")
        self.assertEqual(doc_number.next_number("PROP", [PROP1, DocNumber("PROP", 7), DocNumber("TP", 9)]),
                         DocNumber("PROP", 8))
        self.assertEqual(batch_core.as_pn("PROP-0001"), PROP1)

    def test_prefixes(self):
        self.assertEqual(doc_number.check_prefix(" prop "), "PROP")
        for bad in ("", "1AB", "TOOLONGXX", "A-B", "ECO", "t"):
            self.assertRaises(PNError, doc_number.check_prefix, bad)

    def test_types_are_checked(self):
        good = [doc_types.DocType("prop", "Propulsion Document", "prop"), doc_types.DocType("tp", "Test Procedure", "TP")]
        doc_types.validate(good)
        self.assertEqual(good[0].prefix, "PROP")
        with self.assertRaisesRegex(doc_types.DocTypeError, "both use"):
            doc_types.validate(good + [doc_types.DocType("p2", "Other", "PROP")])
        with self.assertRaisesRegex(doc_types.DocTypeError, "needs a name"):
            doc_types.validate([doc_types.DocType("x", " ", "X")])
        self.assertEqual(doc_types.make_key("Propulsion Document", {"propulsion_document"}), "propulsion_document_2")
        with self.assertRaisesRegex(doc_types.DocTypeError, "Hide it"):
            doc_types.check_kept(good, good[1:], {"prop": 2})

    def test_a_document_record_is_written_and_read_back(self):
        record = record_model.Record(PROP1, "Igniter test", "Alex", "t", doc_type="prop")
        data = record.to_dict()
        self.assertEqual((data["number"], data["doc_type"]), ("PROP-0001", "prop"))
        again = record_model.Record.from_dict(data)
        self.assertEqual((again.pn, again.is_document, again.uses_cad), (PROP1, True, False))
        self.assertEqual(record_store.record_relpath(PROP1), "DOC-logs/PROP-0001.yaml")

    def test_workflow_actions_follow_what_is_selected(self):
        self.assertEqual(workflow_templates.for_targets("release", [PROP1]), "release_document")
        self.assertEqual(workflow_templates.for_targets("release", [PART]), "release")
        self.assertEqual(workflow_templates.base_action("void_document"), "void")
        with self.assertRaisesRegex(workflow_templates.WorkflowError, "not both"):
            workflow_templates.for_targets("release", [PART, PROP1])


def a_file(test, name, text):
    folder = Path(tempfile.mkdtemp())
    test.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and folder.rmdir())
    path = folder / name
    path.write_text(text)
    return path


class WhereLinked(unittest.TestCase):
    """The part revisions that link to a document, read from the parts' records (no git needed)."""

    def test_every_linking_part_revision_is_found(self):
        from litterbox.core.part_number import PN
        with tempfile.TemporaryDirectory() as repo:
            for base, documents in ((1, {"A": ["PROP-0001"], "B": ["PROP-0001", "TP-0001"]}), (2, {"A": ["TP-0001"]}),
                                    (3, {})):
                record = record_model.Record(PN("HCR", base, 1), "Part", "Alex", "2026-10-01T10:00:00Z",
                                             documents=documents)
                path = record_store.record_path(repo, record.pn)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(record_model.dump(record), encoding="utf-8")
            (Path(repo) / "PN-logs" / "HCR-00009-001.yaml").write_text("not: [a record", encoding="utf-8")
            self.assertEqual(doc_links.where_linked(repo, PROP1), [(PN("HCR", 1, 1), "A"), (PN("HCR", 1, 1), "B")])
            self.assertEqual(doc_links.where_linked(repo, "TP-0001"),
                             [(PN("HCR", 1, 1), "B"), (PN("HCR", 2, 1), "A")])
            self.assertEqual(doc_links.where_linked(repo, "PROP-0002"), [])


@SKIP_ON_WINDOWS
class DocumentFlow(CreateFixture, unittest.TestCase):
    def add_type(self, repo):
        doc_types.edit_types(repo, lambda types: types.append(doc_types.DocType("prop", "Propulsion Document", "PROP")),
                             "Document types")

    def test_a_document_is_numbered_filed_released_and_revised(self):
        with self.user("Alex"):
            self.add_type(self.a)
            self.assertEqual(config.load(self.a)["min_litterbox_version"], doc_types.MIN_VERSION)
            number = doc_create.new_document(self.a, "prop", "Igniter test procedure")
            self.assertEqual(number, PROP1)
            self.assertEqual(doc_create.new_document(self.a, "prop", "Second"), DocNumber("PROP", 2))
            checkout.checkout(self.a, number)
            added = doc_files.add_files(self.a, number, [a_file(self, "plan.docx", "v1"), a_file(self, "plan.pdf", "v1")])
            self.assertEqual(added, ["documents/PROP-0001_A.docx", "documents/PROP-0001_A.pdf"])
            with self.assertRaisesRegex(LitterboxError, "already has"):
                doc_files.add_files(self.a, number, [a_file(self, "new.docx", "v2")])
            checkin.checkin(self.a, number, "First draft")
            rows = {row.pn: row for row in part_status.get_status(self.a, documents=True)}
            self.assertEqual((rows[number].kind, rows[number].doc_type), ("ok", "prop"))
            lifecycle.release(self.a, number)
            self.assertFalse(record_store.load(self.a, number).exports)        # no STEP/PDF wanted for a document
            new = revise.revise(self.a, number, "Update", backend=object(), log=lambda *_: None)
            self.assertEqual(sorted(new), ["documents/PROP-0001_B.docx", "documents/PROP-0001_B.pdf"])
            doc_files.remove_file(self.a, number, "documents/PROP-0001_B.pdf")
            checkin.checkin(self.a, number, "No PDF this time")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue((self.b / "documents/PROP-0001_A.pdf").exists())
            self.assertFalse((self.b / "documents/PROP-0001_B.pdf").exists())
            self.assertEqual((self.b / "documents/PROP-0001_B.docx").read_text(), "v1")

    def test_undo_puts_a_removed_file_back(self):
        with self.user("Alex"):
            self.add_type(self.a)
            number = doc_create.new_document(self.a, "prop", "Plan")
            checkout.checkout(self.a, number)
            doc_files.add_files(self.a, number, [a_file(self, "plan.txt", "v1")])
            checkin.checkin(self.a, number, "Plan")
            checkout.checkout(self.a, number)
            doc_files.remove_file(self.a, number, "documents/PROP-0001_A.txt")
            undoing.undo_checkout(self.a, number)
            self.assertEqual((self.a / "documents/PROP-0001_A.txt").read_text(), "v1")
            self.assertEqual(self.locks(self.a), {})

    def test_links_are_made_on_a_checked_out_part_and_carried_by_revise(self):
        with self.user("Alex"):
            self.add_type(self.a)
            number = doc_create.new_document(self.a, "prop", "Plan")
            with self.assertRaisesRegex(LitterboxError, "checked out"):
                doc_links.link(self.a, PART, number)
            checkout.checkout(self.a, PART)
            self.assertTrue(doc_links.link(self.a, PART, number))
            checkin.checkin(self.a, PART, "Linked its plan", allow_unchanged=True)
            lifecycle.release(self.a, PART)
            revise.revise(self.a, PART, "Next", backend=FakeCopier(), log=lambda *_: None)
            record = record_store.load(self.a, PART)
            self.assertEqual((record_links.linked(record, "A"), record_links.linked(record)), (["PROP-0001"], ["PROP-0001"]))
            doc_links.unlink(self.a, PART, number)
            self.assertEqual(record_links.linked(record_store.load(self.a, PART)), [])


class FakeCopier:
    """Stands in for SolidWorks in Revise: copies the file."""

    def copy(self, src, dst):
        Path(dst).write_bytes(Path(src).read_bytes())

    def references(self, path):
        return []

    def repoint(self, *args):
        return True

    def close(self):
        pass


@SKIP_ON_WINDOWS
class DocumentWorkflows(Fixture, unittest.TestCase):
    def test_documents_have_their_own_release_workflow(self):
        with self.user("Alex"):
            doc_types.edit_types(self.a, lambda t: t.append(doc_types.DocType("prop", "Propulsion", "PROP")), "Types")
            number = doc_create.new_document(self.a, "prop", "Plan")
        self.set_template(workflow_templates.RELEASE_DOC)
        self.get_latest("Alex")
        with self.user("Alex"):
            with self.assertRaisesRegex(LitterboxError, "sign-offs"):
                lifecycle.release(self.a, number)
            lifecycle.release(self.a, PART)                         # parts have no release workflow here
        self.request(workflow_templates.RELEASE_DOC, pns=(number,))
        self.do("Alex", workflow_signoff.sign_off, [number])
        self.get_latest("Bea")
        self.assertEqual(self.do("Bea", workflow_signoff.sign_off, [number]).completed, [number])
        self.assertEqual(self.record(number).status, record_model.STATUS_RELEASED)

    def test_a_link_goes_on_a_released_part_at_once_but_comes_off_only_with_sign_offs(self):
        with self.user("Alex"):
            doc_types.edit_types(self.a, lambda t: t.append(doc_types.DocType("prop", "Propulsion", "PROP")), "Types")
            number = doc_create.new_document(self.a, "prop", "Plan")
            lifecycle.release(self.a, PART)
            doc_links.link_released(self.a, PART, number)            # Alex is the Owner
            self.assertEqual(record_links.linked(record_store.load(self.a, PART)), ["PROP-0001"])
        self.get_latest("Bea")
        with self.user("Bea"):
            with self.assertRaisesRegex(LitterboxError, "Admin or a superuser"):
                doc_links.link_released(self.b, PART, number)
        self.set_template(workflow_templates.REMOVE_DOC, rows=((CHIEF,),))
        with self.user("Alex"):
            from litterbox.team import team_editing, team_store
            team_store.edit_directory(self.a, lambda d, who: team_editing.update_person(d, who, "cy", roles=[CHIEF]),
                                      "Cy is Chief")
        self.get_latest("Alex")
        self.request(workflow_templates.REMOVE_DOC, assign=("cy",), reason="Wrong plan", document="PROP-0001")
        self.get_latest("Cy")
        self.assertEqual(self.do("Cy", workflow_signoff.sign_off, [PART]).completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record_links.linked(record)), (record_model.STATUS_RELEASED, []))
        self.assertEqual(record.history[-1]["event"], record_links.EVENT_UNLINKED)


if __name__ == "__main__":
    unittest.main()
