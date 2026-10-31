"""Tests for git/remote.py: how far a copy of the vault is behind its server (commits_behind), and how a sync brings in
what is new without rewriting your own changed files. Most use two copies of a vault and a shared remote, so they need
Linux, macOS or WSL."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support.vault_fixture import PRT, SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.git import runner
from litterbox.parts import create


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


@SKIP_ON_WINDOWS
class Sync(TwoUserVault, unittest.TestCase):
    def setUp(self):
        super().setUp()
        part = self.b / PRT
        os.chmod(part, stat.S_IREAD | stat.S_IWRITE)
        part.write_bytes(b"bea's work")                          # saved in SolidWorks, not checked in
        self.stamp = part.stat().st_mtime_ns

    def sync(self):
        """Sync Bea's copy; return the git commands it ran (their first two words)."""
        ran, run = [], runner.run

        def watch(command, repo, quiet=False):
            ran.append(" ".join(command[1:3]))
            return run(command, repo, quiet)
        with self.user("Bea"), mock.patch.object(runner, "run", watch):
            remote.sync(self.b)
        return ran

    def assert_work_untouched(self):
        part = self.b / PRT
        self.assertEqual(part.read_bytes(), b"bea's work")
        self.assertEqual(part.stat().st_mtime_ns, self.stamp)    # never written, not even with the same contents
        self.assertEqual(git(self.b, "stash", "list"), "")

    def test_nothing_new_leaves_your_files_alone(self):
        ran = self.sync()
        self.assertNotIn("rebase --autostash", ran)
        self.assertNotIn("merge --ff-only", ran)
        self.assert_work_untouched()

    def test_something_new_is_fast_forwarded_around_your_changes(self):
        self.add_created_part(2)
        ran = self.sync()
        self.assertIn("merge --ff-only", ran)
        self.assertNotIn("rebase --autostash", ran)
        self.assertEqual(remote.commits_behind(self.b), 0)
        self.assert_work_untouched()

    def test_a_changed_file_held_open_does_not_stop_it(self):
        # On Windows, a file Python has open can't be deleted, as with SolidWorks: the autostash used to fail on it.
        self.add_created_part(2)
        with open(self.b / PRT, "rb"):
            self.sync()
        self.assertEqual(remote.commits_behind(self.b), 0)
        self.assert_work_untouched()

    def test_your_own_commit_not_yet_uploaded_is_rebased_on_top(self):
        (self.b / "notes.txt").write_text("bea's notes")
        git(self.b, "add", "notes.txt")
        git(self.b, "commit", "-m", "Bea's notes")               # as if its push had failed
        self.add_created_part(2)
        ran = self.sync()
        self.assertIn("rebase --autostash", ran)
        self.assertEqual(git(self.b, "rev-list", "--count", "@{upstream}..HEAD"), "1")
        self.assertEqual((self.b / PRT).read_bytes(), b"bea's work")

    def test_a_rebase_stuck_before_it_began_is_cleared_and_your_changes_kept(self):
        # What a sync left when SolidWorks had the file open: a rebase-merge folder holding only the autostash.
        stash = git(self.b, "stash", "create")
        state = Path(self.b) / git(self.b, "rev-parse", "--git-path", "rebase-merge")
        state.mkdir()
        (state / "autostash").write_text(stash + "\n")
        remote._abort_rebase(self.b)
        self.assertFalse(state.exists())
        self.assertIn(stash, git(self.b, "stash", "list", "--format=%H"))
        self.assertEqual((self.b / PRT).read_bytes(), b"bea's work")
        self.add_created_part(2)
        self.sync()                                              # and syncing works again
        self.assertEqual(remote.commits_behind(self.b), 0)


class Messages(unittest.TestCase):
    def test_a_file_that_could_not_be_replaced_is_named(self):
        error = LitterboxError("Command failed: git rebase --autostash\n\n"
                               "error: unable to unlink old 'cad/HCR-714022-002_A.SLDPRT': Invalid argument\n"
                               "fatal: could not reset --hard")
        message = str(remote._explain_open_files(error))
        self.assertIn("  cad/HCR-714022-002_A.SLDPRT\n", message)
        self.assertIn("Close them and try again.", message)
        self.assertIn("fatal: could not reset --hard", message)  # git's own words are kept for the log

    def test_any_other_error_is_left_as_it_is(self):
        error = LitterboxError("Command failed: git rebase --autostash\n\nCONFLICT (content)")
        self.assertIs(remote._explain_open_files(error), error)

    def test_only_an_unreachable_server_asks_if_you_are_online(self):
        self.assertEqual(create.online_hint(remote.UnreachableError("no route")), " Are you online?")
        self.assertEqual(create.online_hint(LitterboxError("unable to unlink")), "")


if __name__ == "__main__":
    unittest.main()
