"""Tests for checking out, checking in and undoing many parts at once. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import part_changes
from litterbox.git import remote
from litterbox.parts import undoing
from tests.support.batch_fixture import BatchFixture, COUNT, cad


@SKIP_ON_WINDOWS
class BatchCheckoutCheckin(BatchFixture, unittest.TestCase):
    def test_checking_out_many_parts_downloads_once(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(checkout.checkout_many, self.a, self.pns)
        self.assertEqual((len(done), failed), (COUNT, []))
        self.assertEqual(self.count(commands, "git pull"), 1)
        with self.user("Alex"):
            self.assertEqual(len(self.locks(self.a)), COUNT * 3)                   # record + two files each
        for pn, result in done:
            self.assertEqual(result.files, [cad(pn, "SLDDRW"), cad(pn)])
            self.assertEqual(record_store.load(self.a, pn).history[-1]["event"], "checked_out")

    def test_a_part_somebody_else_has_is_reported_and_the_rest_carry_on(self):
        with self.user("Bea"):
            checkout.checkout(self.b, self.pns[2])
        with self.user("Alex"):
            get_latest.get_latest(self.a)
            (done, failed), _ = self.commands(checkout.checkout_many, self.a, self.pns)
            self.assertEqual([pn for pn, _r in done], [p for p in self.pns if p != self.pns[2]])
            self.assertEqual([pn for pn, _why in failed], [self.pns[2]])
            self.assertIn("already checked out by Bea", failed[0][1])
            mine = {path for path, (who, _n) in self.locks(self.a).items() if who == "you"}
            self.assertEqual(len(mine), (COUNT - 1) * 3)                             # nothing left locked for the refused one
            self.assertFalse(any(str(self.pns[2]).lower() in path for path in mine))

    def test_a_part_with_no_record_is_reported(self):
        with self.user("Alex"):
            (done, failed), _ = self.commands(checkout.checkout_many, self.a, [self.pns[0], PN("HCR", 99, 1)])
        self.assertEqual([pn for pn, _r in done], [self.pns[0]])
        self.assertIn("no record for HCR-00099-001", failed[0][1])

    def test_the_same_part_twice_is_checked_out_once(self):
        with self.user("Alex"):
            (done, failed), _ = self.commands(checkout.checkout_many, self.a, [self.pns[0], self.pns[0]])
        self.assertEqual((len(done), failed), (1, []))

    def test_a_failed_download_gives_back_every_lock(self):
        with self.user("Alex"):
            with mock.patch.object(remote, "pull", side_effect=LitterboxError("offline")):
                with self.assertRaises(LitterboxError):
                    checkout.checkout_many(self.a, self.pns)
            self.assertEqual(self.locks(self.a), {})

    def test_checking_in_many_parts_uploads_once_with_a_commit_each(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(checkin.checkin_many, self.a, self.pns, "Tweaks")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertTrue(all(r.uploaded for _pn, r in done))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.count(commands, "git pull"), 1)
            self.assertEqual(self.count(commands, "git commit"), COUNT)
            self.assertEqual(self.locks(self.a), {})
        log = self.remote_log()
        for pn in self.pns:
            self.assertIn(f"{pn}: Tweaks", log)

    def test_saving_progress_on_many_parts_keeps_the_locks(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:3])
            (done, failed), commands = self.commands(checkin.checkin_many, self.a, self.pns[:3], "Half way",
                                                     keep_lock=True)
            self.assertEqual((len(done), failed), (3, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(len(self.locks(self.a)), 9)

    def test_a_part_with_nothing_changed_is_reported_and_the_others_still_upload(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:2])
            (done, failed), _ = self.commands(checkin.checkin_many, self.a, self.pns[:3], "x")
            self.assertEqual([pn for pn, _r in done], self.pns[:2])
            self.assertEqual([pn for pn, _why in failed], [self.pns[2]])
            self.assertIn("No changes were detected", failed[0][1])
            self.assertEqual(len(self.locks(self.a)), 3)                              # the unchanged one is still checked out

    def test_allowing_an_unchanged_part_checks_it_in_anyway(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:1])
            (done, failed), _ = self.commands(checkin.checkin_many, self.a, self.pns[:2], "x",
                                              allow_unchanged={self.pns[1]})
            self.assertEqual((len(done), failed), (2, []))
            self.assertEqual(self.locks(self.a), {})

    def test_a_part_that_is_not_checked_out_is_reported(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            (done, failed), _ = self.commands(checkin.checkin_many, self.a, self.pns[:2], "x")
            self.assertEqual([pn for pn, _r in done], self.pns[:1])
            self.assertIn("don't have", failed[0][1])

    def test_the_change_reports_are_read_together(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:1])
            reports = dict(part_changes.change_reports(self.a, self.pns[:3]))
            self.assertTrue(reports[self.pns[0]].has_changes)
            self.assertFalse(reports[self.pns[1]].has_changes)

    def test_undoing_many_checkouts_restores_the_files_and_unlocks(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(undoing.undo_checkout_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.count(commands, "git restore"), 1)
            for pn in self.pns:
                self.assertEqual((self.a / cad(pn)).read_bytes(), b"v1 " + str(pn).encode())

    def test_undo_reports_a_part_that_is_not_yours(self):
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:1])
            (done, failed), _ = self.commands(undoing.undo_checkout_many, self.a, self.pns[:2])
            self.assertEqual([pn for pn, _r in done], self.pns[:1])
            self.assertIn("don't have", failed[0][1])


if __name__ == "__main__":
    unittest.main()
