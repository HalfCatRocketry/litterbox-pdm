"""Tests for Check In and Save Progress (parts/checkin.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, git, is_writable
from litterbox.records import record_store
from litterbox.errors import LitterboxError, NoChangesError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import part_changes
from litterbox.git import runner
from litterbox.parts import undoing
from tests.support.engine_fixture import EngineFixture


@SKIP_ON_WINDOWS
class CheckInFlow(EngineFixture, unittest.TestCase):
    def test_checkin_uploads_logs_and_unlocks(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            result = checkin.checkin(self.a, PART, "Added fillet")
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [PRT])
            self.assertEqual(self.locks(self.a), {})
            for rel in (PRT, DRW, REC):
                self.assertFalse(is_writable(self.a / rel), rel)
            self.assertIn("HCR-00001-001: Added fillet", self.remote_log())
            last = record_store.load(self.a, PART).history[-1]
            self.assertEqual((last["event"], last["comment"], last["files"]), ("checked_in", "Added fillet", [PRT]))
            self.assertEqual(self.status_of(self.a).kind, "ok")
        with self.user("Bea"):
            self.assertEqual(sorted(get_latest.get_latest(self.b)), sorted([PRT, REC]))
            self.assertEqual((self.b / PRT).read_bytes(), b"version 2")

    def test_save_progress_keeps_the_lock(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            checkin.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertTrue(is_writable(self.a / PRT))
            self.assertIn("HCR-00001-001: Checkpoint", self.remote_log())
            (self.a / PRT).write_bytes(b"version 3")
            checkin.checkin(self.a, PART, "Finished")
            self.assertEqual(self.locks(self.a), {})

    def test_checkin_without_changes_is_refused_and_changes_nothing(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            with self.assertRaises(NoChangesError) as ctx:
                checkin.checkin(self.a, PART, "nothing")
            self.assertEqual(ctx.exception.files, [DRW, PRT])
            self.assertEqual(ctx.exception.pn, PART)
            self.assertEqual(len(self.locks(self.a)), 3)                          # still checked out
            self.assertTrue(is_writable(self.a / PRT))
            self.assertEqual(record_store.load(self.a, PART).history[-1]["event"], "checked_out")
        self.assertEqual(len(self.remote_log()), commits_before)

    def test_checkin_anyway_records_uploads_and_unlocks(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            result = checkin.checkin(self.a, PART, "Looked it over", allow_unchanged=True)
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [])
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / PRT))
            last = record_store.load(self.a, PART).history[-1]
            self.assertEqual((last["event"], last["files"], last["comment"]), ("checked_in", [], "Looked it over"))
            self.assertEqual(record_store.load(self.a, PART).history[-2]["event"], "checked_out")
        self.assertEqual(len(self.remote_log()), commits_before + 1)
        self.assertIn("HCR-00001-001: Looked it over", self.remote_log())
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(record_store.load(self.b, PART).history[-1]["event"], "checked_in")

    def test_save_progress_then_check_in_asks_instead_of_undoing(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            checkin.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            report = part_changes.change_report(self.a, PART)
            self.assertFalse(report.has_changes)
            self.assertEqual(report.unchanged_files, [DRW, PRT])
            with self.assertRaises(NoChangesError):
                checkin.checkin(self.a, PART, "Finished")
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual((self.a / PRT).read_bytes(), b"version 2")           # saved work is intact
            checkin.checkin(self.a, PART, "Finished", allow_unchanged=True)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual((self.a / PRT).read_bytes(), b"version 2")
            self.assertIn("HCR-00001-001: Finished", self.remote_log())

    def test_save_progress_with_nothing_changed_does_nothing(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            result = checkin.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            self.assertFalse(result.uploaded)
            self.assertEqual(len(self.locks(self.a)), 3)
        self.assertEqual(len(self.remote_log()), commits_before)

    def test_change_report(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            report = part_changes.change_report(self.a, PART)
            self.assertEqual((report.has_changes, report.changed_files, report.unchanged_files),
                             (False, [], [DRW, PRT]))
            (self.a / PRT).write_bytes(b"version 2")
            report = part_changes.change_report(self.a, PART)
            self.assertEqual((report.has_changes, report.changed_files, report.unchanged_files),
                             (True, [PRT], [DRW]))
            undoing.undo_checkout(self.a, PART)
            checkout.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace("Front upright", "Upright"), encoding="utf-8")
            report = part_changes.change_report(self.a, PART)
            self.assertTrue(report.has_changes)
            self.assertTrue(report.record_edited)

    def test_checkin_requires_the_checkout(self):
        with self.user("Alex"):
            with self.assertRaises(LitterboxError):
                checkin.checkin(self.a, PART, "oops")
            checkout.checkout(self.a, PART)
        with self.user("Bea"):
            with self.assertRaises(LitterboxError):
                checkin.checkin(self.b, PART, "not mine")

    def test_new_files_are_added_at_checkin(self):
        pn = self.add_created_part(2)
        prt = "cad/HCR-00002-001_A.SLDPRT"
        with self.user("Alex"):
            self.assertEqual(self.status_of(self.a, pn).state, "Created, no CAD files yet")
            self.assertEqual(checkout.checkout(self.a, pn).files, [])
            (self.a / prt).write_bytes(b"brand new")
            result = checkin.checkin(self.a, pn, "First version")
            self.assertEqual(result.files, [prt])
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / prt))
        self.assertIn(prt, git(self.remote, "ls-tree", "-r", "main", "--name-only").splitlines())

    def test_new_files_get_locked_by_save_progress(self):
        pn = self.add_created_part(2)
        prt = "cad/HCR-00002-001_A.SLDPRT"
        with self.user("Alex"):
            checkout.checkout(self.a, pn)
            (self.a / prt).write_bytes(b"brand new")
            checkin.checkin(self.a, pn, "Checkpoint", keep_lock=True)
            self.assertIn(prt.lower(), self.locks(self.a))
            self.assertTrue(is_writable(self.a / prt))

    def test_failed_push_keeps_lock_and_retry_finishes_the_job(self):
        real_run = runner.run
        failures = {"left": 3}                           # all three automatic attempts fail

        def flaky(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and failures["left"] > 0:
                failures["left"] -= 1
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            with mock.patch.object(runner, "run", flaky):
                with self.assertRaises(LitterboxError):
                    checkin.checkin(self.a, PART, "Big change")
            self.assertEqual(len(self.locks(self.a)), 3)                 # still checked out
            self.assertNotIn("HCR-00001-001: Big change", self.remote_log())

            with self.assertRaises(LitterboxError) as ctx:           # undo must not strand the commit
                undoing.undo_checkout(self.a, PART)
            self.assertIn("not uploaded", str(ctx.exception))
            self.assertEqual(len(self.locks(self.a)), 3)

            result = checkin.checkin(self.a, PART, "retry")                  # no new changes, just finish
            self.assertTrue(result.uploaded)
            self.assertIn("HCR-00001-001: Big change", self.remote_log())
            self.assertEqual(self.locks(self.a), {})

    def test_failed_unlock_after_push_can_be_retried(self):
        real_run = runner.run
        broken = {"on": True}

        def flaky(command, repo, quiet=False):
            if command[:3] == ["git", "lfs", "unlock"] and broken["on"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            with mock.patch.object(runner, "run", flaky):
                with self.assertRaises(LitterboxError) as ctx:
                    checkin.checkin(self.a, PART, "Saved")
            self.assertIn("could not be unlocked", str(ctx.exception))
            self.assertIn("HCR-00001-001: Saved", self.remote_log())     # upload did happen
            with self.assertRaises(NoChangesError):                 # nothing new, so it asks first
                checkin.checkin(self.a, PART, "retry")
            checkin.checkin(self.a, PART, "retry", allow_unchanged=True)    # continue: just records it and unlocks
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.remote_log().count("HCR-00001-001: Saved"), 1)

    def test_hand_edited_record_is_uploaded_not_discarded(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace(
                "created_by: Alex", "created_by: Alex Smith"), encoding="utf-8")
            result = checkin.checkin(self.a, PART, "Fixed my name")
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [])                          # no CAD files changed
            self.assertEqual(record_store.load(self.a, PART).created_by, "Alex Smith")
            self.assertEqual(record_store.load(self.a, PART).history[-1]["event"], "checked_in")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Fixed my name", self.remote_log())
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(record_store.load(self.b, PART).created_by, "Alex Smith")

    def test_hand_edited_record_with_save_progress_keeps_the_lock(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace(
                "Front upright", "Front upright, right hand"), encoding="utf-8")
            self.assertTrue(checkin.checkin(self.a, PART, "Better description", keep_lock=True).uploaded)
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual(record_store.load(self.a, PART).name, "Front upright, right hand")

    def test_broken_record_edit_is_never_discarded(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            path = self.a / REC
            path.write_text("just: [broken\n", encoding="utf-8")
            with self.assertRaises(LitterboxError):
                checkin.checkin(self.a, PART, "oops")
            self.assertEqual(path.read_text(encoding="utf-8"), "just: [broken\n")   # still there
            self.assertEqual(len(self.locks(self.a)), 3)                            # still checked out


if __name__ == "__main__":
    unittest.main()
