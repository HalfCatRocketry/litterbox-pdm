"""Tests that a part saved after Check In was pressed is not uploaded (util/file_snapshot.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from tests.support.vault_fixture import SKIP_ON_WINDOWS
from litterbox.records import record_store
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.git import remote
from tests.support.batch_fixture import BatchFixture, COUNT, cad


@SKIP_ON_WINDOWS
class BatchFileChanges(BatchFixture, unittest.TestCase):
    def test_a_part_saved_after_the_click_is_refused_and_stays_checked_out(self):
        from litterbox.util import file_snapshot
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            snap = self.snapshot(self.pns)
            (self.a / cad(self.pns[1])).write_bytes(b"saved again, after the click")
            record_before = (self.a / record_store.record_relpath(self.pns[1])).read_bytes()
            (done, failed), _ = self.commands(checkin.checkin_many, self.a, self.pns, "Tweaks", snapshot=snap)
            self.assertEqual([pn for pn, _r in done], [p for p in self.pns if p != self.pns[1]])
            self.assertEqual([pn for pn, _why in failed], [self.pns[1]])
            self.assertIn("changed after you pressed Check In", failed[0][1])
            self.assertIn("still checked out to you", failed[0][1])
            mine = {path for path, (who, _n) in self.locks(self.a).items() if who == "you"}
            self.assertIn(cad(self.pns[1]).lower(), mine)               # its locks are kept
            self.assertEqual(len(mine), 3)                              # and nobody else's were
            self.assertEqual((self.a / record_store.record_relpath(self.pns[1])).read_bytes(), record_before)
        self.assertEqual(file_snapshot._ACTIVE, [])                     # released

    def test_the_part_can_be_checked_in_again_afterwards(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            snap = self.snapshot(self.pns[:1])
            (self.a / cad(self.pns[0])).write_bytes(b"saved after the click")
            _done, failed = checkin.checkin_many(self.a, self.pns[:1], "Try 1", snapshot=snap)
            self.assertEqual(len(failed), 1)
            done, failed = checkin.checkin_many(self.a, self.pns[:1], "Try 2", snapshot=self.snapshot(self.pns[:1]))
            self.assertEqual((len(done), failed), (1, []))
            self.assertEqual(self.locks(self.a), {})

    def test_a_snapshot_with_no_change_lets_everything_through(self):
        from litterbox.util import file_snapshot
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            done, failed = checkin.checkin_many(self.a, self.pns, "Tweaks", snapshot=self.snapshot(self.pns))
            self.assertEqual((len(done), failed), (COUNT, []))
        self.assertEqual(file_snapshot._ACTIVE, [])

    def test_save_progress_is_meant_for_working_so_a_later_save_is_fine(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:2])
            snap = self.snapshot(self.pns[:2])
            (self.a / cad(self.pns[0])).write_bytes(b"kept working, saved again")
            done, failed = checkin.checkin_many(self.a, self.pns[:2], "Checkpoint", keep_lock=True, snapshot=snap)
            self.assertEqual((len(done), failed), (2, []))

    def test_a_download_in_between_does_not_look_like_a_save(self):
        from tests.support.vault_fixture import PART, PRT
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:2])
            snap = self.snapshot(self.pns[:2])
        with self.user("Bea"):                                          # somebody else uploads something
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"Bea's change")
            checkin.checkin(self.b, PART, "Bea")
        with self.user("Alex"):
            before = (self.a / cad(self.pns[0])).stat().st_mtime_ns
            remote.pull(self.a)                                           # git stashes and restores Alex's edits
            self.assertNotEqual((self.a / cad(self.pns[0])).stat().st_mtime_ns, before)   # so the time did change
            done, failed = checkin.checkin_many(self.a, self.pns[:2], "Tweaks", snapshot=snap)
            self.assertEqual((len(done), failed), (2, []))

    def test_a_save_in_the_middle_of_reading_is_caught_per_part(self):
        self.check_save_during_add()

    def test_a_save_in_the_middle_of_reading_is_caught_in_a_one_commit_batch(self):
        self.use_style("per_batch")
        self.check_save_during_add()


if __name__ == "__main__":
    unittest.main()
