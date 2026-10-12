"""
Two-user tests for litterbox_engine.py.

These run the real engine against real git repos (a bare "remote" plus one
clone per simulated user), but use tests/fake_git_lfs.py in place of Git LFS.
That means they check Litterbox's logic, NOT your host's LFS lock support.
(Your own two-account test on the real host still has to do that.)

They need a Unix-like system (Linux, macOS, or WSL) and are skipped on Windows.
Run from the app folder with:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable  # noqa: E402

import litterbox_engine as eng  # noqa: E402
import registry  # noqa: E402
from pn import PN  # noqa: E402


@SKIP_ON_WINDOWS
class EngineFlow(TwoUserVault, unittest.TestCase):
    # -- check out ---------------------------------------------------------
    def test_files_start_read_only(self):
        for repo in (self.a, self.b):
            for rel in (PRT, DRW, REC):
                self.assertFalse(is_writable(repo / rel), rel)

    def test_checkout_locks_everything_and_logs_it(self):
        with self.user("Alex"):
            result = eng.checkout(self.a, PART)
            self.assertEqual(result.files, [DRW, PRT])
            self.assertEqual(result.changed_upstream, [])
            self.assertEqual(sorted(self.locks(self.a)), sorted([DRW.lower(), PRT.lower(), REC.lower()]))
            for rel in (PRT, DRW, REC):
                self.assertTrue(is_writable(self.a / rel), rel)
            history = registry.load(self.a, PART).history
            self.assertEqual(history[-1]["event"], "checked_out")
            self.assertEqual(history[-1]["files"], [DRW, PRT])
            self.assertEqual(self.status_of(self.a).kind, "mine")

    def test_second_user_is_refused_and_nothing_is_left_locked(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
        with self.user("Bea"):
            eng.get_latest(self.b)
            row = self.status_of(self.b)
            self.assertEqual((row.kind, row.locked_by), ("theirs", "Alex"))
            with self.assertRaises(eng.LitterboxError) as ctx:
                eng.checkout(self.b, PART)
            self.assertIn("already checked out by Alex", str(ctx.exception))
            self.assertFalse(is_writable(self.b / PRT))
            # Alex's three locks are all that exist
            self.assertEqual({v[1] for v in eng.get_locks(self.b, strict=True).values()}, {"Alex"})

    def test_checkout_downloads_newer_version_and_reports_it(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            eng.checkin(self.a, PART, "Changed it")
        with self.user("Bea"):                         # Bea has not pulled yet
            result = eng.checkout(self.b, PART)
            self.assertEqual(result.changed_upstream, [PRT])
            self.assertEqual((self.b / PRT).read_bytes(), b"version 2")

    def test_failed_checkout_rolls_back_its_locks(self):
        with self.user("Alex"):
            real_run = eng.run

            def failing(command, repo, quiet=False):
                if command[:3] == ["git", "lfs", "lock"] and command[3] == DRW:
                    raise eng.LitterboxError("simulated failure")
                return real_run(command, repo, quiet)

            with mock.patch.object(eng, "run", failing):
                with self.assertRaises(eng.LitterboxError):
                    eng.checkout(self.a, PART)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(registry.load(self.a, PART).history[-1]["event"], "created")

    # -- check in ----------------------------------------------------------
    def test_checkin_uploads_logs_and_unlocks(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            result = eng.checkin(self.a, PART, "Added fillet")
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [PRT])
            self.assertEqual(self.locks(self.a), {})
            for rel in (PRT, DRW, REC):
                self.assertFalse(is_writable(self.a / rel), rel)
            self.assertIn("HCR-00001-001: Added fillet", self.remote_log())
            last = registry.load(self.a, PART).history[-1]
            self.assertEqual((last["event"], last["comment"], last["files"]), ("checked_in", "Added fillet", [PRT]))
            self.assertEqual(self.status_of(self.a).kind, "ok")
        with self.user("Bea"):
            self.assertEqual(sorted(eng.get_latest(self.b)), sorted([PRT, REC]))
            self.assertEqual((self.b / PRT).read_bytes(), b"version 2")

    def test_save_progress_keeps_the_lock(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            eng.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertTrue(is_writable(self.a / PRT))
            self.assertIn("HCR-00001-001: Checkpoint", self.remote_log())
            (self.a / PRT).write_bytes(b"version 3")
            eng.checkin(self.a, PART, "Finished")
            self.assertEqual(self.locks(self.a), {})

    def test_checkin_without_changes_is_refused_and_changes_nothing(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            with self.assertRaises(eng.NoChangesError) as ctx:
                eng.checkin(self.a, PART, "nothing")
            self.assertEqual(ctx.exception.files, [DRW, PRT])
            self.assertEqual(ctx.exception.pn, PART)
            self.assertEqual(len(self.locks(self.a)), 3)                          # still checked out
            self.assertTrue(is_writable(self.a / PRT))
            self.assertEqual(registry.load(self.a, PART).history[-1]["event"], "checked_out")
        self.assertEqual(len(self.remote_log()), commits_before)

    def test_checkin_anyway_records_uploads_and_unlocks(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            result = eng.checkin(self.a, PART, "Looked it over", allow_unchanged=True)
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [])
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / PRT))
            last = registry.load(self.a, PART).history[-1]
            self.assertEqual((last["event"], last["files"], last["comment"]), ("checked_in", [], "Looked it over"))
            self.assertEqual(registry.load(self.a, PART).history[-2]["event"], "checked_out")
        self.assertEqual(len(self.remote_log()), commits_before + 1)
        self.assertIn("HCR-00001-001: Looked it over", self.remote_log())
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertEqual(registry.load(self.b, PART).history[-1]["event"], "checked_in")

    def test_save_progress_then_check_in_asks_instead_of_undoing(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            eng.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            report = eng.change_report(self.a, PART)
            self.assertFalse(report.has_changes)
            self.assertEqual(report.unchanged_files, [DRW, PRT])
            with self.assertRaises(eng.NoChangesError):
                eng.checkin(self.a, PART, "Finished")
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual((self.a / PRT).read_bytes(), b"version 2")           # saved work is intact
            eng.checkin(self.a, PART, "Finished", allow_unchanged=True)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual((self.a / PRT).read_bytes(), b"version 2")
            self.assertIn("HCR-00001-001: Finished", self.remote_log())

    def test_save_progress_with_nothing_changed_does_nothing(self):
        commits_before = len(self.remote_log())
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            result = eng.checkin(self.a, PART, "Checkpoint", keep_lock=True)
            self.assertFalse(result.uploaded)
            self.assertEqual(len(self.locks(self.a)), 3)
        self.assertEqual(len(self.remote_log()), commits_before)

    def test_change_report(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            report = eng.change_report(self.a, PART)
            self.assertEqual((report.has_changes, report.changed_files, report.unchanged_files),
                             (False, [], [DRW, PRT]))
            (self.a / PRT).write_bytes(b"version 2")
            report = eng.change_report(self.a, PART)
            self.assertEqual((report.has_changes, report.changed_files, report.unchanged_files),
                             (True, [PRT], [DRW]))
            eng.undo_checkout(self.a, PART)
            eng.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace("Front upright", "Upright"), encoding="utf-8")
            report = eng.change_report(self.a, PART)
            self.assertTrue(report.has_changes)
            self.assertTrue(report.record_edited)

    def test_checkin_requires_the_checkout(self):
        with self.user("Alex"):
            with self.assertRaises(eng.LitterboxError):
                eng.checkin(self.a, PART, "oops")
            eng.checkout(self.a, PART)
        with self.user("Bea"):
            with self.assertRaises(eng.LitterboxError):
                eng.checkin(self.b, PART, "not mine")

    def test_new_files_are_added_at_checkin(self):
        pn = self.add_created_part(2)
        prt = "cad/HCR-00002-001_A.SLDPRT"
        with self.user("Alex"):
            self.assertEqual(self.status_of(self.a, pn).state, "Created, no CAD files yet")
            self.assertEqual(eng.checkout(self.a, pn).files, [])
            (self.a / prt).write_bytes(b"brand new")
            result = eng.checkin(self.a, pn, "First version")
            self.assertEqual(result.files, [prt])
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / prt))
        self.assertIn(prt, git(self.remote, "ls-tree", "-r", "main", "--name-only").splitlines())

    def test_new_files_get_locked_by_save_progress(self):
        pn = self.add_created_part(2)
        prt = "cad/HCR-00002-001_A.SLDPRT"
        with self.user("Alex"):
            eng.checkout(self.a, pn)
            (self.a / prt).write_bytes(b"brand new")
            eng.checkin(self.a, pn, "Checkpoint", keep_lock=True)
            self.assertIn(prt.lower(), self.locks(self.a))
            self.assertTrue(is_writable(self.a / prt))

    def test_failed_push_keeps_lock_and_retry_finishes_the_job(self):
        real_run = eng.run
        failures = {"left": 3}                           # all three automatic attempts fail

        def flaky(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and failures["left"] > 0:
                failures["left"] -= 1
                raise eng.LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            with mock.patch.object(eng, "run", flaky):
                with self.assertRaises(eng.LitterboxError):
                    eng.checkin(self.a, PART, "Big change")
            self.assertEqual(len(self.locks(self.a)), 3)                 # still checked out
            self.assertNotIn("HCR-00001-001: Big change", self.remote_log())

            with self.assertRaises(eng.LitterboxError) as ctx:           # undo must not strand the commit
                eng.undo_checkout(self.a, PART)
            self.assertIn("not uploaded", str(ctx.exception))
            self.assertEqual(len(self.locks(self.a)), 3)

            result = eng.checkin(self.a, PART, "retry")                  # no new changes, just finish
            self.assertTrue(result.uploaded)
            self.assertIn("HCR-00001-001: Big change", self.remote_log())
            self.assertEqual(self.locks(self.a), {})

    def test_failed_unlock_after_push_can_be_retried(self):
        real_run = eng.run
        broken = {"on": True}

        def flaky(command, repo, quiet=False):
            if command[:3] == ["git", "lfs", "unlock"] and broken["on"]:
                raise eng.LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            with mock.patch.object(eng, "run", flaky):
                with self.assertRaises(eng.LitterboxError) as ctx:
                    eng.checkin(self.a, PART, "Saved")
            self.assertIn("could not be unlocked", str(ctx.exception))
            self.assertIn("HCR-00001-001: Saved", self.remote_log())     # upload did happen
            with self.assertRaises(eng.NoChangesError):                 # nothing new, so it asks first
                eng.checkin(self.a, PART, "retry")
            eng.checkin(self.a, PART, "retry", allow_unchanged=True)    # continue: just records it and unlocks
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.remote_log().count("HCR-00001-001: Saved"), 1)

    def test_hand_edited_record_is_uploaded_not_discarded(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace(
                "created_by: Alex", "created_by: Alex Smith"), encoding="utf-8")
            result = eng.checkin(self.a, PART, "Fixed my name")
            self.assertTrue(result.uploaded)
            self.assertEqual(result.files, [])                          # no CAD files changed
            self.assertEqual(registry.load(self.a, PART).created_by, "Alex Smith")
            self.assertEqual(registry.load(self.a, PART).history[-1]["event"], "checked_in")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Fixed my name", self.remote_log())
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertEqual(registry.load(self.b, PART).created_by, "Alex Smith")

    def test_hand_edited_record_with_save_progress_keeps_the_lock(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            path = self.a / REC
            path.write_text(path.read_text(encoding="utf-8").replace(
                "Front upright", "Front upright, right hand"), encoding="utf-8")
            self.assertTrue(eng.checkin(self.a, PART, "Better description", keep_lock=True).uploaded)
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual(registry.load(self.a, PART).name, "Front upright, right hand")

    def test_broken_record_edit_is_never_discarded(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            path = self.a / REC
            path.write_text("just: [broken\n", encoding="utf-8")
            with self.assertRaises(eng.LitterboxError):
                eng.checkin(self.a, PART, "oops")
            self.assertEqual(path.read_text(encoding="utf-8"), "just: [broken\n")   # still there
            self.assertEqual(len(self.locks(self.a)), 3)                            # still checked out

    # -- undo --------------------------------------------------------------
    def test_undo_restores_files_and_forgets_the_checkout(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"scribbles")
            (self.a / "cad/HCR-00001-001_A.STEP").write_bytes(b"never uploaded")
            left = eng.undo_checkout(self.a, PART)
            self.assertEqual(left, ["cad/HCR-00001-001_A.STEP"])
            self.assertEqual((self.a / PRT).read_bytes(), b"version 1")
            self.assertTrue((self.a / "cad/HCR-00001-001_A.STEP").exists())   # not deleted
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(registry.load(self.a, PART).history[-1]["event"], "created")
            self.assertFalse(is_writable(self.a / PRT))

    # -- a brand-new part, saved before it was checked out -------------------
    def test_new_part_with_unclaimed_file_can_be_checked_out(self):
        import create
        with self.user("Bea"):
            pn = create.new_part(self.b, "Fresh")
            eng.checkout(self.b, pn)                   # what the New Part button now does
            self.assertEqual(self.status_of(self.b, pn).kind, "mine")
            eng.undo_checkout(self.b, pn)
            new_file = self.b / "cad" / f"{pn}_A.SLDPRT"
            new_file.write_bytes(b"saved before checkout")
            self.assertEqual(self.status_of(self.b, pn).kind, "unclaimed")
            result = eng.checkout(self.b, pn)          # claims the file that is already there
            self.assertEqual(result.files, [f"cad/{pn}_A.SLDPRT"])
            self.assertEqual(self.status_of(self.b, pn).kind, "mine")

    # -- status ------------------------------------------------------------
    def test_status_kinds(self):
        with self.user("Bea"):
            self.assertEqual(self.status_of(self.b).kind, "ok")
            (self.b / PRT).chmod(0o644)
            (self.b / PRT).write_bytes(b"edited without checkout")
            self.assertEqual(self.status_of(self.b).kind, "unclaimed")
            git(self.b, "restore", "--", PRT)
            (self.b / DRW).chmod(0o644)
            (self.b / DRW).write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 9\n")
            self.assertEqual(self.status_of(self.b).kind, "missing")

    # -- release / reopen / void -------------------------------------------
    def test_release_and_reopen_cycle(self):
        with self.user("Alex"):
            plan = eng.release_plan(self.a, PART)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(plan.files, [DRW, PRT])
            self.assertEqual(eng.release(self.a, PART), [DRW, PRT])
            self.assertEqual(registry.load(self.a, PART).status, "released")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Released", self.remote_log())
            self.assertFalse(is_writable(self.a / REC))
            self.assertEqual(self.status_of(self.a).kind, "released")
            with self.assertRaises(eng.LitterboxError):
                eng.checkout(self.a, PART)                   # released parts can't be checked out
            self.assertEqual(self.locks(self.a), {})
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertEqual(self.status_of(self.b).kind, "released")
            with self.assertRaises(eng.LitterboxError):      # reason is required, and nothing is left behind
                eng.reopen(self.b, PART, "  ")
            self.assertEqual(self.locks(self.b), {})
            eng.reopen(self.b, PART, "Bore diameter wrong")
            record = registry.load(self.b, PART)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(record.history[-1]["reason"], "Bore diameter wrong")
            self.assertIn("HCR-00001-001: Unreleased - Bore diameter wrong", self.remote_log())
            eng.checkout(self.b, PART)                       # editable again

    def test_release_is_blocked_while_checked_out_or_changed(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half done")
        with self.user("Bea"):
            eng.get_latest(self.b)
            plan = eng.release_plan(self.b, PART)
            self.assertFalse(plan.ok)
            self.assertTrue(any("checked out by Alex" in p for p in plan.problems), plan.problems)
            with self.assertRaises(eng.LitterboxError):
                eng.release(self.b, PART)
        with self.user("Alex"):
            plan = eng.release_plan(self.a, PART)
            self.assertTrue(any("not checked in" in p for p in plan.problems), plan.problems)

    def test_release_is_blocked_when_behind_the_vault(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            eng.checkin(self.a, PART, "Changed")
        with self.user("Bea"):                               # Bea has not pulled
            plan = eng.release_plan(self.b, PART)
            self.assertTrue(any("Get Latest" in p for p in plan.problems), plan.problems)

    def test_make_cots_freezes_checkout_and_logs_it(self):
        with self.user("Alex"):
            plan = eng.make_cots_plan(self.a, PART)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(eng.make_cots(self.a, PART), [DRW, PRT])
            record = registry.load(self.a, PART)
            self.assertTrue(record.cots)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(record.history[-1]["event"], "made_cots")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Made COTS", self.remote_log())
            row = self.status_of(self.a)
            self.assertEqual((row.kind, row.cots), ("cots", True))
            with self.assertRaises(eng.LitterboxError):
                eng.checkout(self.a, PART)                   # a COTS part can't be checked out
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(eng.make_cots_plan(self.a, PART).ok)     # and can't be made COTS twice
            self.assertFalse(eng.release_plan(self.a, PART).ok)       # nor released
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertEqual(self.status_of(self.b).kind, "cots")

    def test_make_cots_is_blocked_while_checked_out_changed_or_behind(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half done")
        with self.user("Bea"):
            eng.get_latest(self.b)
            plan = eng.make_cots_plan(self.b, PART)
            self.assertTrue(any("checked out by Alex" in p for p in plan.problems), plan.problems)
            with self.assertRaises(eng.LitterboxError):
                eng.make_cots(self.b, PART)
            self.assertFalse(registry.load(self.b, PART).cots)
        with self.user("Alex"):
            self.assertTrue(any("not checked in" in p for p in eng.make_cots_plan(self.a, PART).problems))
            eng.checkin(self.a, PART, "Changed")
        with self.user("Bea"):                               # Bea has not pulled
            self.assertTrue(any("Get Latest" in p for p in eng.make_cots_plan(self.b, PART).problems))

    def test_make_cots_needs_cad_files_and_released_parts_are_refused(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            self.assertFalse(eng.make_cots_plan(self.a, pn).ok)
            eng.release(self.a, PART)
            plan = eng.make_cots_plan(self.a, PART)
            self.assertTrue(any("released" in p for p in plan.problems), plan.problems)

    def test_reopen_undoes_make_cots(self):
        with self.user("Alex"):
            eng.make_cots(self.a, PART)
        with self.user("Bea"):
            eng.get_latest(self.b)
            with self.assertRaises(eng.LitterboxError):
                eng.reopen(self.b, PART, " ")
            eng.reopen(self.b, PART, "Not a purchased part")
            self.assertFalse(registry.load(self.b, PART).cots)
            self.assertEqual(self.status_of(self.b).kind, "ok")
            self.assertIn("HCR-00001-001: Unreleased - Not a purchased part", self.remote_log())
            eng.checkout(self.b, PART)

    def put_revisions(self, base, working, released, revisions=("A", "B")):
        """Alex's copy: a part with files for several revisions, the record saying which is working/released."""
        pn = self.add_created_part(base)
        with self.user("Alex"):
            for rev in revisions:
                (self.a / f"cad/HCR-{base:05d}-001_{rev}.SLDPRT").write_bytes(f"rev {rev}".encode())
            record = registry.load(self.a, pn)
            record.revision, record.released_revision = working, released
            if released == working:
                record.status = "released"
            path = self.a / f"PN-logs/HCR-{base:05d}-001.yaml"
            path.chmod(0o644)
            registry.save(self.a, record)
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Set up revisions")
            git(self.a, "push")
            eng.enforce_read_only(self.a)
        return pn

    def test_a_working_revision_next_to_a_released_one(self):
        pn = self.put_revisions(2, working="B", released="A")
        with self.user("Alex"):
            row = self.status_of(self.a, pn)
            self.assertEqual((row.revision, row.released_revision), ("B", "A"))
            self.assertEqual(row.files, ["cad/HCR-00002-001_B.SLDPRT"])
            self.assertEqual(sorted(row.revisions), ["A", "B"])
            self.assertEqual((row.kind, row.state), ("ok", "Available (Rev A released)"))
            result = eng.checkout(self.a, pn)
            self.assertEqual(result.files, ["cad/HCR-00002-001_B.SLDPRT"])
            self.assertIn("cad/hcr-00002-001_b.sldprt", self.locks(self.a))
            self.assertNotIn("cad/hcr-00002-001_a.sldprt", self.locks(self.a))      # the released revision is never locked
            self.assertTrue(is_writable(self.a / "cad/HCR-00002-001_B.SLDPRT"))
            self.assertFalse(is_writable(self.a / "cad/HCR-00002-001_A.SLDPRT"))
            self.assertEqual(self.status_of(self.a, pn).state, "Checked out by you (Rev A released)")

    def test_releasing_the_working_revision_records_it(self):
        pn = self.put_revisions(2, working="B", released="A")
        with self.user("Alex"):
            plan = eng.release_plan(self.a, pn)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(plan.files, ["cad/HCR-00002-001_B.SLDPRT"])
            eng.release(self.a, pn)
            record = registry.load(self.a, pn)
            self.assertEqual((record.revision, record.released_revision, record.status), ("B", "B", "released"))
            self.assertEqual(record.history[-1]["revision"], "B")
            self.assertEqual(self.status_of(self.a, pn).kind, "released")

    def test_files_for_another_revision_are_pointed_out(self):
        pn = self.put_revisions(3, working="A", released="", revisions=("B",))
        with self.user("Alex"):
            row = self.status_of(self.a, pn)
            self.assertEqual((row.kind, row.files), ("stray", []))
            self.assertIn("No files for Rev A", row.state)
            self.assertIn("Rev B", row.state)

    def test_edit_details_needs_checkout_and_uploads_with_checkin(self):
        with self.user("Alex"):
            with self.assertRaises(eng.LitterboxError):
                eng.edit_details(self.a, PART, "New name", "")           # not checked out
            eng.checkout(self.a, PART)
            self.assertFalse(eng.edit_details(self.a, PART, registry.load(self.a, PART).name,
                                              registry.load(self.a, PART).description))
            self.assertTrue(eng.edit_details(self.a, PART, "Renamed part", "A description"))
            row = self.status_of(self.a)
            self.assertEqual((row.name, row.description), ("Renamed part", "A description"))
            self.assertTrue(eng.change_report(self.a, PART).record_edited)   # even with no CAD changes
            eng.checkin(self.a, PART, "Fixed the name")
            self.assertIn("HCR-00001-001: Fixed the name", self.remote_log())
        with self.user("Bea"):
            eng.get_latest(self.b)
            record = registry.load(self.b, PART)
            self.assertEqual((record.name, record.description), ("Renamed part", "A description"))
            self.assertIn("edited", [e["event"] for e in record.history])
            with self.assertRaises(eng.LitterboxError):                       # Alex no longer holds it
                eng.edit_details(self.b, PART, "Bea's name", "")

    def test_undo_checkout_throws_away_edited_details(self):
        with self.user("Alex"):
            eng.checkout(self.a, PART)
            original = registry.load(self.a, PART).name
            eng.edit_details(self.a, PART, "Oops", "")
            eng.undo_checkout(self.a, PART)
            self.assertEqual(registry.load(self.a, PART).name, original)

    def test_cots_part_can_still_be_voided(self):
        with self.user("Alex"):
            eng.make_cots(self.a, PART)
            eng.void(self.a, PART, "Wrong part")
            self.assertEqual(self.status_of(self.a).kind, "void")

    def test_release_needs_cad_files(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            plan = eng.release_plan(self.a, pn)
            self.assertFalse(plan.ok)

    def test_void_keeps_number_and_blocks_checkout(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            eng.void(self.a, pn, "Never needed")
            self.assertEqual(self.status_of(self.a, pn).kind, "void")
            self.assertIn(2, registry.used_bases(self.a))
            with self.assertRaises(eng.LitterboxError):
                eng.checkout(self.a, pn)
            self.assertEqual(self.locks(self.a), {})

    def test_failed_push_during_release_restores_the_record(self):
        real_run = eng.run

        def failing(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise eng.LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(eng, "run", failing):
                with self.assertRaises(eng.LitterboxError):
                    eng.release(self.a, PART)
            record = registry.load(self.a, PART)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(len(record.history), 1)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    def test_missing_git_name(self):
        with self.user("Alex"):
            git(self.a, "config", "user.name", "")
            with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}):
                with self.assertRaises(eng.LitterboxError) as ctx:
                    eng.checkout(self.a, PART)
            self.assertIn("user.name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
