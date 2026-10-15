"""Tests for voiding, releasing and making many parts COTS at once (parts/batch_core.edit_records). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, git
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.parts import planning
from litterbox.git import remote
from tests.support.batch_fixture import BatchFixture, COUNT, cad


@SKIP_ON_WINDOWS
class BatchRecordEdits(BatchFixture, unittest.TestCase):
    def test_voiding_many_parts_downloads_and_uploads_once(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(lifecycle.void_many, self.a, self.pns, "Not needed")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.count(commands, "git pull"), 2)           # once to start, once inside the upload
            self.assertEqual(self.count(commands, "git commit"), 1)               # one commit for all of them
            self.assertEqual(self.locks(self.a), {})
        message = git(self.a, "log", "-1", "--format=%B")
        self.assertTrue(message.startswith(f"{COUNT} parts: Voided - Not needed"))
        for pn in self.pns:
            self.assertEqual(record_store.load(self.a, pn).status, record_model.STATUS_VOID)
            self.assertIn(f"{pn}: Voided - Not needed", message)                 # every part is named in it
            self.assertIn(f"PN-logs/{pn}.yaml", git(self.a, "show", "--name-only", "--format=", "HEAD"))

    def test_one_part_keeps_its_own_commit_message(self):
        with self.user("Alex"):
            lifecycle.void_many(self.a, self.pns[:1], "Not needed")
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), f"{self.pns[0]}: Voided - Not needed")

    def test_a_part_somebody_has_checked_out_is_skipped_when_voiding(self):
        with self.user("Bea"):
            checkout.checkout(self.b, self.pns[1])
        with self.user("Alex"):
            get_latest.get_latest(self.a)
            (done, failed), _ = self.commands(lifecycle.void_many, self.a, self.pns, "Not needed")
            self.assertEqual(len(done), COUNT - 1)
            self.assertEqual([pn for pn, _why in failed], [self.pns[1]])
            self.assertEqual(record_store.load(self.a, self.pns[1]).status, record_model.STATUS_IN_WORK)

    def test_a_refused_edit_leaves_that_record_alone_and_the_rest_are_changed(self):
        with self.user("Alex"):
            lifecycle.void_many(self.a, self.pns[:1], "first")
            (done, failed), _ = self.commands(lifecycle.void_many, self.a, self.pns[:2], "again")      # the first is void already
            self.assertEqual([pn for pn, _r in done], self.pns[1:2])
            self.assertEqual([pn for pn, _why in failed], self.pns[:1])
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_a_failed_upload_puts_everything_back(self):
        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with mock.patch.object(remote, "push_with_retry", side_effect=LitterboxError("offline")):
                with self.assertRaises(LitterboxError):
                    lifecycle.void_many(self.a, self.pns, "Not needed")
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)               # the commits were taken back
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})
            for pn in self.pns:
                self.assertEqual(record_store.load(self.a, pn).status, record_model.STATUS_IN_WORK)

    def test_unreleasing_and_releasing_many_parts(self):
        with self.user("Alex"):
            plans = planning.release_plans(self.a, self.pns)
            self.assertTrue(all(p.ok for p in plans))
            (done, failed), commands = self.commands(lifecycle.release_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.count(commands, "git fetch"), 1)                    # the vault was looked at once
            (done, failed), commands = self.commands(lifecycle.reopen_many, self.a, self.pns, "Oops")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
        self.assertIn(f"{self.pns[0]}: Unreleased - Oops", git(self.a, "log", "-1", "--format=%B"))

    def test_release_skips_the_parts_that_cannot_go(self):
        with self.user("Alex"):
            checkout.checkout(self.a, self.pns[0])
            (self.a / cad(self.pns[0])).write_bytes(b"edited")
            (done, failed), _ = self.commands(lifecycle.release_many, self.a, self.pns[:3])
            self.assertEqual([pn for pn, _r in done], self.pns[1:3])
            self.assertEqual([pn for pn, _why in failed], self.pns[:1])
            self.assertIn("can't be released yet", failed[0][1])

    def test_making_many_parts_cots(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(lifecycle.make_cots_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertTrue(all(record_store.load(self.a, pn).cots for pn in self.pns))

    def test_one_failing_edit_with_atomic_changes_nothing(self):
        def good(record, user):
            record_lifecycle.mark_void(record, user, "x")

        def bad(record, user):
            raise record_model.RegistryError("not allowed")

        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with self.assertRaises(record_model.RegistryError):
                batch_core.edit_records(self.a, [(self.pns[0], "void", good, "m1"), (self.pns[1], "void", bad, "m2")],
                                  atomic=True)
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(record_store.load(self.a, self.pns[0]).status, record_model.STATUS_IN_WORK)

    def test_locks_are_taken_several_at_a_time_and_a_refusal_names_its_file(self):
        with self.user("Bea"):
            lfs_locks.lock(self.b, "PN-logs/HCR-00003-001.yaml", "HCR-00003-001")
        with self.user("Alex"):
            wanted = [(f"PN-logs/{pn}.yaml", str(pn)) for pn in self.pns]
            got = lfs_locks.lock_many(self.a, wanted)
            self.assertEqual([path for path, error in got.items() if error is not None],
                             ["PN-logs/HCR-00003-001.yaml"])
            self.assertIn("already checked out by Bea", str(got["PN-logs/HCR-00003-001.yaml"]))
            self.assertEqual(len(self.locks(self.a)), COUNT)


if __name__ == "__main__":
    unittest.main()
