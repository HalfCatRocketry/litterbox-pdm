"""Tests for Check Out (parts/checkout.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, is_writable
from litterbox.records import record_store
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import lfs_locks
from litterbox.git import runner
from tests.support.engine_fixture import EngineFixture


@SKIP_ON_WINDOWS
class CheckOutFlow(EngineFixture, unittest.TestCase):
    def test_files_start_read_only(self):
        for repo in (self.a, self.b):
            for rel in (PRT, DRW, REC):
                self.assertFalse(is_writable(repo / rel), rel)

    def test_checkout_locks_everything_and_logs_it(self):
        with self.user("Alex"):
            result = checkout.checkout(self.a, PART)
            self.assertEqual(result.files, [DRW, PRT])
            self.assertEqual(result.changed_upstream, [])
            self.assertEqual(sorted(self.locks(self.a)), sorted([DRW.lower(), PRT.lower(), REC.lower()]))
            for rel in (PRT, DRW, REC):
                self.assertTrue(is_writable(self.a / rel), rel)
            history = record_store.load(self.a, PART).history
            self.assertEqual(history[-1]["event"], "checked_out")
            self.assertEqual(history[-1]["files"], [DRW, PRT])
            self.assertEqual(self.status_of(self.a).kind, "mine")

    def test_second_user_is_refused_and_nothing_is_left_locked(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            row = self.status_of(self.b)
            self.assertEqual((row.kind, row.locked_by), ("theirs", "Alex"))
            with self.assertRaises(LitterboxError) as ctx:
                checkout.checkout(self.b, PART)
            self.assertIn("already checked out by Alex", str(ctx.exception))
            self.assertFalse(is_writable(self.b / PRT))
            # Alex's three locks are all that exist
            self.assertEqual({v[1] for v in lfs_locks.get_locks(self.b, strict=True).values()}, {"Alex"})

    def test_checkout_downloads_newer_version_and_reports_it(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            checkin.checkin(self.a, PART, "Changed it")
        with self.user("Bea"):                         # Bea has not pulled yet
            result = checkout.checkout(self.b, PART)
            self.assertEqual(result.changed_upstream, [PRT])
            self.assertEqual((self.b / PRT).read_bytes(), b"version 2")

    def test_failed_checkout_rolls_back_its_locks(self):
        with self.user("Alex"):
            real_run = runner.run

            def failing(command, repo, quiet=False):
                if command[:3] == ["git", "lfs", "lock"] and command[3] == DRW:
                    raise LitterboxError("simulated failure")
                return real_run(command, repo, quiet)

            with mock.patch.object(runner, "run", failing):
                with self.assertRaises(LitterboxError):
                    checkout.checkout(self.a, PART)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(record_store.load(self.a, PART).history[-1]["event"], "created")


if __name__ == "__main__":
    unittest.main()
