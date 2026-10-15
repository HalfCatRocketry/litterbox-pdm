"""
Tests for download on demand (parts/downloads.py and the actions that download). Bea's copy was cloned without the
CAD files, like Add org... does; Alex's has everything. They use the fake git-lfs's model of LFS, so they need
Linux, macOS or WSL.
"""

import unittest

from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable

from litterbox.core.part_number import PN
from litterbox.git import lfs_download
from litterbox.git import read_only
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import downloads
from litterbox.parts import lifecycle
from litterbox.parts import planning
from litterbox.parts import undoing
from litterbox.records import record_store
from litterbox.workflows import workflow_request

ASM = PN("HCR", 2, 1)
ASM_FILE = "cad/HCR-00002-001_A.SLDASM"


@SKIP_ON_WINDOWS
class DownloadOnDemand(TwoUserVault, unittest.TestCase):
    ON_DEMAND = True

    def add_assembly_using_the_part(self):
        """Alex adds an assembly whose Rev A uses the part's Rev A, and pushes it; Bea gets the records."""
        with self.user("Alex"):
            (self.a / ASM_FILE).write_bytes(b"assembly 1")
            record = record_store.create_record(self.a, ASM, "Frame", "Alex")
            record.references = {"A": [f"{PART}_A"]}
            record_store.save(self.a, record)
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Add the frame")
            git(self.a, "push")
        git(self.b, "pull")

    def test_a_part_that_is_not_downloaded_keeps_its_status_and_says_so(self):
        with self.user("Bea"):
            row = self.status_of(self.b)
        self.assertEqual((row.kind, row.not_downloaded), ("ok", True))
        self.assertEqual(row.state, "Available (not downloaded)")

    def test_check_out_downloads_the_parts_files(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            row = self.status_of(self.b)
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW]), [])
        self.assertEqual((self.b / PRT).read_bytes(), b"version 1")
        self.assertTrue(is_writable(self.b / PRT))
        self.assertEqual((row.kind, row.not_downloaded), ("mine", False))

    def test_check_out_edit_and_check_in_on_a_copy_that_downloads_on_demand(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"version 2 by Bea")
            checkin.checkin(self.b, PART, "Thicker")
        git(self.a, "pull")
        self.assertEqual((self.a / PRT).read_bytes(), b"version 2 by Bea")
        self.assertFalse(read_only.is_pointer(self.b / PRT))                    # Bea keeps her copy
        self.assertEqual(git(self.b, "status", "--porcelain"), "")

    def test_undo_checkout_gives_back_the_downloaded_file(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"a mistake")
            undoing.undo_checkout(self.b, PART)
        self.assertEqual((self.b / PRT).read_bytes(), b"version 1")              # not a pointer
        self.assertFalse(is_writable(self.b / PRT))
        self.assertEqual(git(self.b, "status", "--porcelain"), "")

    def test_release_needs_no_download(self):
        with self.user("Bea"):
            plan = planning.release_plan(self.b, PART)
            self.assertTrue(plan.ok, plan.problems)
            lifecycle.release(self.b, PART)
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW]), [PRT, DRW])   # nothing was downloaded
        self.assertEqual(record_store.load(self.b, PART).status, "released")

    def test_a_workflow_fingerprint_does_not_need_the_file(self):
        self.assertEqual(workflow_request.file_hashes(self.b, [PRT]), workflow_request.file_hashes(self.a, [PRT]))
        self.assertTrue(read_only.is_pointer(self.b / PRT))

    def test_opening_an_assembly_downloads_the_parts_it_uses(self):
        self.add_assembly_using_the_part()
        self.assertEqual(downloads.files_to_open(self.b, ASM, "A"), sorted([ASM_FILE, DRW, PRT]))
        with self.user("Bea"):
            done = downloads.download_for_open(self.b, ASM, "A")
        self.assertEqual(sorted(done), sorted([ASM_FILE, DRW, PRT]))
        self.assertEqual(lfs_download.stubs(self.b, [ASM_FILE, DRW, PRT]), [])
        self.assertEqual(downloads.download_for_open(self.b, ASM, "A"), [])     # already there

    def test_opening_a_part_downloads_only_that_part(self):
        self.add_assembly_using_the_part()
        with self.user("Bea"):
            downloads.download_for_open(self.b, PART, "A")
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW, ASM_FILE]), [ASM_FILE])

    def test_switching_to_everything_downloads_everything_once(self):
        with self.user("Bea"):
            self.assertTrue(downloads.apply_mode(self.b, on_demand=False))
            self.assertFalse(downloads.apply_mode(self.b, on_demand=False))    # already so: nothing to do
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW]), [])
        self.assertFalse(lfs_download.is_on_demand(self.b))

    def test_records_are_always_there(self):
        self.assertTrue((self.b / REC).is_file())
        self.assertEqual(record_store.load(self.b, PART).name, "Front upright")


if __name__ == "__main__":
    unittest.main()
