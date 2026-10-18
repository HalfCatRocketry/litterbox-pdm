"""
Tests for repairing git-lfs's lock cache (.git/lfs/lockcache.db) when it is damaged (git/lfs_locks.py).

A damaged cache makes every git-lfs lock command fail, so Litterbox could no longer read locks, check out or check
in. The first group runs anywhere; the second uses the two-user vault and a fake git-lfs that fails the way the real
one does, so it needs Linux, macOS or WSL.
"""

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import runner
from litterbox.parts import checkout

DAMAGED = ("Command failed: git lfs locks --verify --json\n\nUnable to create lock system: lock cache initialization: "
           "problem reading updated key/value data from C:\\vault\\.git\\lfs\\lockcache.db: gob: bad data: field "
           "numbers out of bounds")


class Healing(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        (self.repo / ".git" / "lfs").mkdir(parents=True)
        self.cache = lfs_locks.lock_cache_path(self.repo)
        self.cache.write_bytes(b"broken")
        self.log = []
        patcher = mock.patch.object(diagnostics, "LOG", self.log.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_damaged_cache_message_is_recognised(self):
        self.assertTrue(lfs_locks.cache_is_damaged(LitterboxError(DAMAGED)))
        self.assertFalse(lfs_locks.cache_is_damaged(LitterboxError("Lock failed: already locked by Bea")))

    def test_the_damaged_file_is_moved_aside_and_kept(self):
        moved = lfs_locks.heal_lock_cache(self.repo)
        self.assertFalse(self.cache.exists())
        self.assertEqual(moved.read_bytes(), b"broken")
        self.assertTrue(moved.name.startswith("lockcache.db.broken-"))
        self.assertIn("lock cache was damaged", self.log[0])
        self.assertIsNone(lfs_locks.heal_lock_cache(self.repo))            # nothing left to move

    def test_a_command_that_fails_on_the_cache_is_tried_once_more(self):
        calls = []

        def git_lfs(command, repo, quiet=False):
            calls.append(self.cache.exists())
            if self.cache.exists():
                raise LitterboxError(DAMAGED)
            return "{}"
        with mock.patch.object(runner, "run", git_lfs):
            self.assertEqual(lfs_locks.run_lfs(["git", "lfs", "locks", "--verify", "--json"], self.repo), "{}")
        self.assertEqual(calls, [True, False])

    def test_other_failures_are_not_retried(self):
        with mock.patch.object(runner, "run", side_effect=LitterboxError("Lock failed: already locked by Bea")) as run:
            with self.assertRaises(LitterboxError):
                lfs_locks.run_lfs(["git", "lfs", "lock", "x"], self.repo)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.cache.exists())

    def test_several_commands_failing_at_once_move_it_only_once(self):
        start = threading.Barrier(6)
        results = []

        def heal():
            start.wait()
            results.append(lfs_locks.heal_lock_cache(self.repo))
        threads = [threading.Thread(target=heal) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(list(self.cache.parent.glob("lockcache.db.broken-*"))), 1)


@SKIP_ON_WINDOWS
class HealingInAVault(TwoUserVault, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.log = []
        patcher = mock.patch.object(diagnostics, "LOG", self.log.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = lfs_locks.lock_cache_path(self.a)
        self.cache.parent.mkdir(parents=True, exist_ok=True)

    def damage(self):
        self.cache.write_bytes(b"broken")

    def test_the_lock_list_is_read_after_repairing_the_cache(self):
        self.damage()
        with self.user("Alex"):
            self.assertEqual(lfs_locks.get_locks(self.a, strict=True), {})
        self.assertFalse(self.cache.exists())
        self.assertTrue(any("lock cache was damaged" in line for line in self.log))

    def test_check_out_works_with_a_damaged_cache(self):
        self.damage()
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            self.assertEqual(sorted(self.locks(self.a)), sorted(p.lower() for p in (DRW, PRT, REC)))

    def test_a_healthy_cache_is_left_alone(self):
        self.cache.write_bytes(b"fine")
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
        self.assertEqual(self.cache.read_bytes(), b"fine")
        self.assertFalse(any("lock cache" in line for line in self.log))


if __name__ == "__main__":
    unittest.main()
