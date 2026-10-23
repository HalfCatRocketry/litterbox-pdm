"""Tests for Export Files and where an export may go. No git: a vault folder with records and files is enough."""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from litterbox.core.part_number import PN
from litterbox.exporting import export_folder
from litterbox.exporting import part_files_export as export
from litterbox.parts import downloads
from litterbox.records import record_store
from tests.support.gui_fakes import replace
from tests.support import temp_folders

PART, ASM = PN("HCR", 1, 1), PN("HCR", 2, 1)
def temporary_folder(test):
    """A new folder, removed after the test (its files made writable first: some are read-only, as in a vault)."""
    folder = Path(tempfile.mkdtemp())

    def remove():
        for path in folder.rglob("*"):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if path.is_dir() else 0))
        temp_folders.remove(folder)
    test.addCleanup(remove)
    return folder


POINTER = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 9\n"


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_folder(self)
        self.root = self.tmp / "Litterbox"
        (self.root / "vault").mkdir(parents=True)

    def test_a_folder_outside_litterbox_and_any_repository_is_fine(self):
        (self.tmp / "out").mkdir()
        self.assertEqual(export_folder.check(self.tmp / "out", self.root), (self.tmp / "out").resolve())

    def test_litterbox_itself_and_everything_in_it_are_refused(self):
        for inside in (self.root, self.root / "vault"):
            with self.assertRaisesRegex(export_folder.ExportError, "outside"):
                export_folder.check(inside, self.root)

    def test_a_folder_whose_name_only_starts_like_litterbox_is_fine(self):
        (self.tmp / "Litterbox-copies").mkdir()
        export_folder.check(self.tmp / "Litterbox-copies", self.root)

    def test_a_folder_inside_any_git_repository_is_refused(self):
        (self.tmp / "project" / ".git").mkdir(parents=True)
        (self.tmp / "project" / "sub").mkdir()
        with self.assertRaisesRegex(export_folder.ExportError, "git repository"):
            export_folder.check(self.tmp / "project" / "sub", self.root)

    def test_no_folder_or_a_missing_one_is_refused(self):
        with self.assertRaisesRegex(export_folder.ExportError, "Choose a folder"):
            export_folder.check("  ", self.root)
        with self.assertRaisesRegex(export_folder.ExportError, "no folder"):
            export_folder.check(self.tmp / "nope", self.root)


class ExportFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_folder(self)
        self.root, self.repo, self.out = self.tmp / "Litterbox", self.tmp / "Litterbox" / "vault", self.tmp / "out"
        (self.repo / "cad").mkdir(parents=True)
        self.out.mkdir()
        record_store.create_record(self.repo, PART, "Bracket", "Alex")
        record_store.create_record(self.repo, ASM, "Frame", "Alex")
        for pn, released, rev, references in ((PART, "A", "B", {}), (ASM, "", "A", {"A": ["HCR-00001-001_A"]})):
            record = record_store.load(self.repo, pn)
            record.released_revision, record.revision, record.references = released, rev, references
            record_store.save(self.repo, record)
        for name in ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.STEP",
                     "HCR-00001-001_A.PDF", "HCR-00001-001_B.SLDPRT", "HCR-00002-001_A.SLDASM"):
            path = self.repo / "cad" / name
            path.write_text(f"contents of {name}\n", encoding="utf-8")
            os.chmod(path, stat.S_IREAD)                    # vault files are read-only on disk

    def test_released_revision_of_the_kinds_chosen(self):
        chosen = export.plan(self.repo, [PART], [export.STEP, export.PDF])
        self.assertEqual(chosen.files, ["cad/HCR-00001-001_A.PDF", "cad/HCR-00001-001_A.STEP"])
        self.assertEqual(chosen.revisions, {PART: "A"})
        self.assertEqual(export.plan(self.repo, [PART], [export.MODEL], export.WORKING).files,
                         ["cad/HCR-00001-001_B.SLDPRT"])

    def test_a_revision_picked_by_its_letter(self):
        chosen = export.plan(self.repo, [PART], [export.MODEL, export.DRAWING], "A")
        self.assertEqual(chosen.files, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"])
        self.assertEqual((chosen.revisions, chosen.notes), ({PART: "A"}, []))

    def test_a_part_never_released_gives_its_working_revision_and_says_so(self):
        chosen = export.plan(self.repo, [ASM], [export.MODEL])
        self.assertEqual(chosen.files, ["cad/HCR-00002-001_A.SLDASM"])
        self.assertIn("never been released", chosen.notes[0])

    def test_an_assembly_can_bring_the_part_revisions_it_uses(self):
        chosen = export.plan(self.repo, [ASM], [export.MODEL, export.DRAWING], with_used=True)
        self.assertEqual(chosen.files, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT",
                                        "cad/HCR-00002-001_A.SLDASM"])

    def test_no_kinds_or_no_matching_files(self):
        with self.assertRaises(export_folder.ExportError):
            export.plan(self.repo, [PART], [])
        chosen = export.plan(self.repo, [ASM], [export.PDF])
        self.assertEqual(chosen.files, [])
        self.assertIn("no files of the kinds chosen", chosen.notes[-1])

    def test_copies_are_ordinary_writable_files_and_the_vault_is_untouched(self):
        files = export.plan(self.repo, [PART], export.KINDS).files
        names = export.export(self.repo, files, self.out, self.root)
        self.assertEqual(sorted(names), sorted(Path(f).name for f in files))
        copy = self.out / "HCR-00001-001_A.STEP"
        self.assertEqual(copy.read_text(encoding="utf-8"), "contents of HCR-00001-001_A.STEP\n")
        self.assertTrue(os.access(copy, os.W_OK))
        self.assertFalse(os.access(self.repo / "cad" / "HCR-00001-001_A.STEP", os.W_OK))

    def test_files_already_in_the_folder_are_replaced_only_when_asked(self):
        files = ["cad/HCR-00001-001_A.STEP"]
        (self.out / "HCR-00001-001_A.STEP").write_text("old", encoding="utf-8")
        os.chmod(self.out / "HCR-00001-001_A.STEP", stat.S_IREAD)
        self.assertEqual(export.already_there(files, self.out), ["HCR-00001-001_A.STEP"])
        with self.assertRaisesRegex(export_folder.ExportError, "already has 1"):
            export.export(self.repo, files, self.out, self.root)
        export.export(self.repo, files, self.out, self.root, replace=True)
        self.assertIn("contents of", (self.out / "HCR-00001-001_A.STEP").read_text(encoding="utf-8"))

    def test_never_into_the_vault_or_litterbox(self):
        with self.assertRaisesRegex(export_folder.ExportError, "outside"):
            export.export(self.repo, ["cad/HCR-00001-001_A.STEP"], self.repo, self.root)

    def test_files_not_downloaded_are_downloaded_first(self):
        stub = self.repo / "cad" / "HCR-00001-001_A.PDF"
        os.chmod(stub, stat.S_IWRITE | stat.S_IREAD)
        stub.write_bytes(POINTER)
        asked = []

        def fake_download(repo, rels, label="files"):
            asked.append(list(rels))
            stub.write_text("the real PDF\n", encoding="utf-8")
        replace(self, downloads, "download_files", fake_download)
        export.export(self.repo, ["cad/HCR-00001-001_A.PDF"], self.out, self.root)
        self.assertEqual(asked, [["cad/HCR-00001-001_A.PDF"]])
        self.assertEqual((self.out / "HCR-00001-001_A.PDF").read_text(encoding="utf-8"), "the real PDF\n")

    def test_a_file_that_could_not_be_downloaded_stops_the_export(self):
        stub = self.repo / "cad" / "HCR-00001-001_A.PDF"
        os.chmod(stub, stat.S_IWRITE | stat.S_IREAD)
        stub.write_bytes(POINTER)
        replace(self, downloads, "download_files", lambda repo, rels, label="files": [])
        with self.assertRaisesRegex(export_folder.ExportError, "could not be downloaded"):
            export.export(self.repo, ["cad/HCR-00001-001_A.PDF"], self.out, self.root)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
