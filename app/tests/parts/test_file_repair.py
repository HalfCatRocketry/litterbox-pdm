"""
Tests for parts/file_repair.py (Vault > Repair Files): files on this computer that don't match the vault's copy, and
that you don't have checked out, get the vault's copy back. Two copies of a vault and the fake git-lfs, so they need
Linux, macOS or WSL (or LITTERBOX_GIT_TESTS=1 on Windows).
"""

import unittest
import unittest.mock

from tests.support.vault_fixture import DRW, PRT, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable

from litterbox.git import lfs_download
from litterbox.git import read_only
from litterbox.parts import file_repair


def damage(path, data=b"\0\0 half a file"):
    path.chmod(0o644)
    path.write_bytes(data)


@SKIP_ON_WINDOWS
class RepairFiles(TwoUserVault, unittest.TestCase):
    def test_a_vault_that_matches_has_nothing_to_repair(self):
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [])

    def test_a_damaged_file_gets_the_vaults_copy_back_read_only(self):
        damage(self.b / PRT)
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [PRT])
            result = file_repair.repair(self.b, [PRT])
            self.assertEqual((result.repaired, result.failed, result.not_downloaded), ([PRT], {}, []))
            self.assertEqual((self.b / PRT).read_bytes(), b"version 1")
            self.assertFalse(is_writable(self.b / PRT))
            self.assertEqual(file_repair.find(self.b), [])
        self.assertEqual(git(self.b, "status", "--porcelain"), "")

    def test_a_missing_file_is_put_back(self):
        read_only.delete_file(self.b / DRW)
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [DRW])
            file_repair.repair(self.b, [DRW])
        self.assertEqual((self.b / DRW).read_bytes(), b"drawing 1")

    def test_your_checked_out_changes_are_never_touched(self):
        with self.user("Bea"):
            git(self.b, "lfs", "lock", PRT)
            (self.b / PRT).write_bytes(b"Bea's work")
            self.assertEqual(file_repair.find(self.b), [])
            self.assertEqual(file_repair.repair(self.b, [PRT]).repaired, [])     # even if asked
        self.assertEqual((self.b / PRT).read_bytes(), b"Bea's work")

    def test_a_file_someone_else_has_checked_out_can_be_repaired(self):
        with self.user("Alex"):
            git(self.a, "lfs", "lock", PRT)
        damage(self.b / PRT)
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [PRT])
            self.assertEqual(file_repair.repair(self.b, [PRT]).repaired, [PRT])
        self.assertEqual((self.b / PRT).read_bytes(), b"version 1")

    def test_a_file_git_cannot_put_back_is_named_and_the_rest_still_repaired(self):
        damage(self.b / PRT)
        damage(self.b / DRW)
        real = file_repair.runner.run

        def held_open(command, repo, quiet=False):
            if command[:2] == ["git", "restore"] and PRT in command:
                raise file_repair.LitterboxError("Command failed\n\nerror: unable to unlink old 'cad/x': Invalid argument")
            return real(command, repo, quiet=quiet)

        with self.user("Bea"), unittest.mock.patch.object(file_repair.runner, "run", side_effect=held_open):
            result = file_repair.repair(self.b, [DRW, PRT])
        self.assertEqual(result.repaired, [DRW])
        self.assertIn("unable to unlink", result.failed[PRT])
        self.assertEqual((self.b / DRW).read_bytes(), b"drawing 1")


@SKIP_ON_WINDOWS
class RepairOnDemand(TwoUserVault, unittest.TestCase):
    ON_DEMAND = True

    def test_a_damaged_download_is_downloaded_again(self):
        with self.user("Bea"):
            lfs_download.download(self.b, [PRT])
        damage(self.b / PRT, b"vers")                       # cut off part-way
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [PRT])
            self.assertEqual(file_repair.repair(self.b, [PRT]).repaired, [PRT])
            self.assertEqual(file_repair.find(self.b), [])
        self.assertEqual((self.b / PRT).read_bytes(), b"version 1")
        self.assertFalse(is_writable(self.b / PRT))
        self.assertTrue(read_only.is_pointer(self.b / DRW))         # files that weren't touched stay as they were

    def test_pointers_are_not_damage(self):
        with self.user("Bea"):
            self.assertEqual(file_repair.find(self.b), [])


if __name__ == "__main__":
    unittest.main()
