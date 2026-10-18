"""Tests for git/remote.py's commits_behind: how far a copy of the vault is behind its server. They use two copies
of a vault and a shared remote, so they need Linux, macOS or WSL."""

import tempfile
import unittest
from pathlib import Path

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault

from litterbox.git import remote


@SKIP_ON_WINDOWS
class Behind(TwoUserVault, unittest.TestCase):
    def test_counts_what_others_uploaded_and_nothing_after_getting_it(self):
        self.assertEqual(remote.commits_behind(self.b), 0)
        self.add_created_part(2)                                  # Alex uploads a new part
        self.add_created_part(3)
        self.assertEqual(remote.commits_behind(self.b), 2)
        with self.user("Bea"):
            remote.pull(self.b)
        self.assertEqual(remote.commits_behind(self.b), 0)
        self.assertEqual(remote.commits_behind(self.a), 0)         # Alex has them already

    def test_a_folder_that_is_not_a_vault_says_it_cannot_tell(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(remote.commits_behind(Path(folder)))


if __name__ == "__main__":
    unittest.main()
