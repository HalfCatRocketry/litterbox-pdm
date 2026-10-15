"""
Tests for git/lfs_download.py and pulls in a vault that downloads on demand. Bea's copy is cloned without the CAD
files (like Add org... does); Alex's has everything. They use the fake git-lfs's model of LFS, so they need Linux,
macOS or WSL.
"""

import hashlib
import unittest

from tests.support.vault_fixture import DRW, PRT, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable

from litterbox.git import lfs_download
from litterbox.git import read_only
from litterbox.git import remote


@SKIP_ON_WINDOWS
class OnDemand(TwoUserVault, unittest.TestCase):
    ON_DEMAND = True

    def test_a_new_copy_has_pointers_and_knows_it_downloads_on_demand(self):
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW]), [PRT, DRW])
        self.assertEqual(lfs_download.stubs(self.a, [PRT, DRW]), [])
        self.assertTrue(lfs_download.is_on_demand(self.b))
        self.assertFalse(lfs_download.is_on_demand(self.a))
        self.assertEqual(git(self.b, "status", "--porcelain"), "")             # pointers are not "changes"

    def test_the_pointer_says_what_the_file_is(self):
        self.assertEqual(lfs_download.pointer_oid(self.b / PRT), hashlib.sha256(b"version 1").hexdigest())
        self.assertIsNone(lfs_download.pointer_oid(self.a / PRT))              # a real file is not a pointer

    def test_download_fetches_just_those_files_and_keeps_them_read_only(self):
        with self.user("Bea"):
            self.assertEqual(lfs_download.download(self.b, [PRT]), [PRT])
        self.assertEqual((self.b / PRT).read_bytes(), b"version 1")
        self.assertTrue(read_only.is_pointer(self.b / DRW))
        self.assertFalse(is_writable(self.b / PRT))
        self.assertEqual(git(self.b, "status", "--porcelain"), "")
        self.assertEqual(lfs_download.download(self.b, [PRT]), [])               # nothing left to do

    def test_downloaded_files_stay_downloaded_through_a_pull_and_the_rest_stay_pointers(self):
        with self.user("Bea"):
            lfs_download.download(self.b, [PRT])
        with self.user("Alex"):
            for rel, data in ((PRT, b"version 2"), (DRW, b"drawing 2")):
                (self.a / rel).chmod(0o644)
                (self.a / rel).write_bytes(data)
            git(self.a, "commit", "-am", "Alex changes both")
            git(self.a, "push")
        with self.user("Bea"):
            remote.pull(self.b)
        self.assertEqual((self.b / PRT).read_bytes(), b"version 2")           # had it: updated and downloaded
        self.assertTrue(read_only.is_pointer(self.b / DRW))                     # never had it: still a pointer
        self.assertEqual(git(self.b, "status", "--porcelain"), "")

    def test_download_everything(self):
        with self.user("Bea"):
            lfs_download.download_everything(self.b)
        self.assertEqual(lfs_download.stubs(self.b, [PRT, DRW]), [])

    def test_switching_a_copy_between_on_demand_and_everything(self):
        lfs_download.set_on_demand(self.a, True)
        self.assertTrue(lfs_download.is_on_demand(self.a))
        lfs_download.set_on_demand(self.a, False)
        self.assertFalse(lfs_download.is_on_demand(self.a))


if __name__ == "__main__":
    unittest.main()
