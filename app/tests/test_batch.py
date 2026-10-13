"""
Tests for doing one action on many parts at once (the *_many functions in litterbox_engine.py).

The point of them is speed: a batch downloads once and uploads once, instead of once per part, and the files'
locks are taken and released several at a time. These tests count the commands to prove it, and check that a
problem with one part leaves the rest alone and that a failed upload leaves nothing half done.

They need Linux, macOS or WSL (they use the fake git-lfs in tests/fake_git_lfs.py).
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git  # noqa: E402

import litterbox_engine as eng  # noqa: E402
import registry  # noqa: E402
from pn import PN  # noqa: E402

COUNT = 5


def cad(pn, ext="SLDPRT", rev="A"):
    return f"cad/{pn}_{rev}.{ext}"


@SKIP_ON_WINDOWS
class BatchActions(TwoUserVault, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.pns = [PN("HCR", n, 1) for n in range(2, 2 + COUNT)]          # five more parts, each with two files
        for pn in self.pns:
            registry.create_record(self.a, pn, f"Part {pn.base}", "Alex")
            (self.a / cad(pn)).write_bytes(b"v1 " + str(pn).encode())
            (self.a / cad(pn, "SLDDRW")).write_bytes(b"d1 " + str(pn).encode())
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Add parts")
        git(self.a, "push")
        with self.user("Alex"):
            eng.enforce_read_only(self.a)
        with self.user("Bea"):
            eng.get_latest(self.b)

    def commands(self, func, *args, **kwargs):
        """Run func, returning (result, [every command it ran])."""
        seen, real = [], eng.run

        def recording(command, repo, quiet=False):
            seen.append(" ".join(command))
            return real(command, repo, quiet)

        with mock.patch.object(eng, "run", recording):
            result = func(*args, **kwargs)
        return result, seen

    @staticmethod
    def count(commands, prefix):
        return sum(1 for c in commands if c.startswith(prefix))

    def subjects(self, repo=None):
        return git(repo or self.a, "log", "--format=%s", "-20").splitlines()

    # -- check out -----------------------------------------------------------
    def test_checking_out_many_parts_downloads_once(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(eng.checkout_many, self.a, self.pns)
        self.assertEqual((len(done), failed), (COUNT, []))
        self.assertEqual(self.count(commands, "git pull"), 1)
        with self.user("Alex"):
            self.assertEqual(len(self.locks(self.a)), COUNT * 3)                   # record + two files each
        for pn, result in done:
            self.assertEqual(result.files, [cad(pn, "SLDDRW"), cad(pn)])
            self.assertEqual(registry.load(self.a, pn).history[-1]["event"], "checked_out")

    def test_a_part_somebody_else_has_is_reported_and_the_rest_carry_on(self):
        with self.user("Bea"):
            eng.checkout(self.b, self.pns[2])
        with self.user("Alex"):
            eng.get_latest(self.a)
            (done, failed), _ = self.commands(eng.checkout_many, self.a, self.pns)
            self.assertEqual([pn for pn, _r in done], [p for p in self.pns if p != self.pns[2]])
            self.assertEqual([pn for pn, _why in failed], [self.pns[2]])
            self.assertIn("already checked out by Bea", failed[0][1])
            mine = {path for path, (who, _n) in self.locks(self.a).items() if who == "you"}
            self.assertEqual(len(mine), (COUNT - 1) * 3)                             # nothing left locked for the refused one
            self.assertFalse(any(str(self.pns[2]).lower() in path for path in mine))

    def test_a_part_with_no_record_is_reported(self):
        with self.user("Alex"):
            (done, failed), _ = self.commands(eng.checkout_many, self.a, [self.pns[0], PN("HCR", 99, 1)])
        self.assertEqual([pn for pn, _r in done], [self.pns[0]])
        self.assertIn("no record for HCR-00099-001", failed[0][1])

    def test_the_same_part_twice_is_checked_out_once(self):
        with self.user("Alex"):
            (done, failed), _ = self.commands(eng.checkout_many, self.a, [self.pns[0], self.pns[0]])
        self.assertEqual((len(done), failed), (1, []))

    def test_a_failed_download_gives_back_every_lock(self):
        with self.user("Alex"):
            with mock.patch.object(eng, "_pull", side_effect=eng.LitterboxError("offline")):
                with self.assertRaises(eng.LitterboxError):
                    eng.checkout_many(self.a, self.pns)
            self.assertEqual(self.locks(self.a), {})

    # -- check in and save progress -------------------------------------------
    def change(self, pns, text=b"changed"):
        for pn in pns:
            (self.a / cad(pn)).write_bytes(text + str(pn).encode())

    def test_checking_in_many_parts_uploads_once_with_a_commit_each(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(eng.checkin_many, self.a, self.pns, "Tweaks")
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
            eng.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:3])
            (done, failed), commands = self.commands(eng.checkin_many, self.a, self.pns[:3], "Half way",
                                                     keep_lock=True)
            self.assertEqual((len(done), failed), (3, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(len(self.locks(self.a)), 9)

    def test_a_part_with_nothing_changed_is_reported_and_the_others_still_upload(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:2])
            (done, failed), _ = self.commands(eng.checkin_many, self.a, self.pns[:3], "x")
            self.assertEqual([pn for pn, _r in done], self.pns[:2])
            self.assertEqual([pn for pn, _why in failed], [self.pns[2]])
            self.assertIn("No changes were detected", failed[0][1])
            self.assertEqual(len(self.locks(self.a)), 3)                              # the unchanged one is still checked out

    def test_allowing_an_unchanged_part_checks_it_in_anyway(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:1])
            (done, failed), _ = self.commands(eng.checkin_many, self.a, self.pns[:2], "x",
                                              allow_unchanged={self.pns[1]})
            self.assertEqual((len(done), failed), (2, []))
            self.assertEqual(self.locks(self.a), {})

    def test_a_part_that_is_not_checked_out_is_reported(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            (done, failed), _ = self.commands(eng.checkin_many, self.a, self.pns[:2], "x")
            self.assertEqual([pn for pn, _r in done], self.pns[:1])
            self.assertIn("don't have", failed[0][1])

    def test_the_change_reports_are_read_together(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:1])
            reports = dict(eng.change_reports(self.a, self.pns[:3]))
            self.assertTrue(reports[self.pns[0]].has_changes)
            self.assertFalse(reports[self.pns[1]].has_changes)

    # -- undo -----------------------------------------------------------------
    def test_undoing_many_checkouts_restores_the_files_and_unlocks(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(eng.undo_checkout_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.count(commands, "git restore"), 1)
            for pn in self.pns:
                self.assertEqual((self.a / cad(pn)).read_bytes(), b"v1 " + str(pn).encode())

    def test_undo_reports_a_part_that_is_not_yours(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:1])
            (done, failed), _ = self.commands(eng.undo_checkout_many, self.a, self.pns[:2])
            self.assertEqual([pn for pn, _r in done], self.pns[:1])
            self.assertIn("don't have", failed[0][1])

    # -- void, unrelease, release, make COTS --------------------------------------
    def test_voiding_many_parts_downloads_and_uploads_once(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(eng.void_many, self.a, self.pns, "Not needed")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.count(commands, "git pull"), 2)           # once to start, once inside the upload
            self.assertEqual(self.count(commands, "git commit"), 1)               # one commit for all of them
            self.assertEqual(self.locks(self.a), {})
        message = git(self.a, "log", "-1", "--format=%B")
        self.assertTrue(message.startswith(f"{COUNT} parts: Voided - Not needed"))
        for pn in self.pns:
            self.assertEqual(registry.load(self.a, pn).status, registry.STATUS_VOID)
            self.assertIn(f"{pn}: Voided - Not needed", message)                 # every part is named in it
            self.assertIn(f"PN-logs/{pn}.yaml", git(self.a, "show", "--name-only", "--format=", "HEAD"))

    def test_one_part_keeps_its_own_commit_message(self):
        with self.user("Alex"):
            eng.void_many(self.a, self.pns[:1], "Not needed")
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), f"{self.pns[0]}: Voided - Not needed")

    def test_a_part_somebody_has_checked_out_is_skipped_when_voiding(self):
        with self.user("Bea"):
            eng.checkout(self.b, self.pns[1])
        with self.user("Alex"):
            eng.get_latest(self.a)
            (done, failed), _ = self.commands(eng.void_many, self.a, self.pns, "Not needed")
            self.assertEqual(len(done), COUNT - 1)
            self.assertEqual([pn for pn, _why in failed], [self.pns[1]])
            self.assertEqual(registry.load(self.a, self.pns[1]).status, registry.STATUS_IN_WORK)

    def test_a_refused_edit_leaves_that_record_alone_and_the_rest_are_changed(self):
        with self.user("Alex"):
            eng.void_many(self.a, self.pns[:1], "first")
            (done, failed), _ = self.commands(eng.void_many, self.a, self.pns[:2], "again")      # the first is void already
            self.assertEqual([pn for pn, _r in done], self.pns[1:2])
            self.assertEqual([pn for pn, _why in failed], self.pns[:1])
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_a_failed_upload_puts_everything_back(self):
        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with mock.patch.object(eng, "_push_with_retry", side_effect=eng.LitterboxError("offline")):
                with self.assertRaises(eng.LitterboxError):
                    eng.void_many(self.a, self.pns, "Not needed")
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)               # the commits were taken back
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})
            for pn in self.pns:
                self.assertEqual(registry.load(self.a, pn).status, registry.STATUS_IN_WORK)

    def test_unreleasing_and_releasing_many_parts(self):
        with self.user("Alex"):
            plans = eng.release_plans(self.a, self.pns)
            self.assertTrue(all(p.ok for p in plans))
            (done, failed), commands = self.commands(eng.release_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.count(commands, "git fetch"), 1)                    # the vault was looked at once
            (done, failed), commands = self.commands(eng.reopen_many, self.a, self.pns, "Oops")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
        self.assertIn(f"{self.pns[0]}: Unreleased - Oops", git(self.a, "log", "-1", "--format=%B"))

    def test_release_skips_the_parts_that_cannot_go(self):
        with self.user("Alex"):
            eng.checkout(self.a, self.pns[0])
            (self.a / cad(self.pns[0])).write_bytes(b"edited")
            (done, failed), _ = self.commands(eng.release_many, self.a, self.pns[:3])
            self.assertEqual([pn for pn, _r in done], self.pns[1:3])
            self.assertEqual([pn for pn, _why in failed], self.pns[:1])
            self.assertIn("can't be released yet", failed[0][1])

    def test_making_many_parts_cots(self):
        with self.user("Alex"):
            (done, failed), commands = self.commands(eng.make_cots_many, self.a, self.pns)
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertTrue(all(registry.load(self.a, pn).cots for pn in self.pns))

    # -- the building blocks ---------------------------------------------------------
    def test_one_failing_edit_with_atomic_changes_nothing(self):
        def good(record, user):
            registry.mark_void(record, user, "x")

        def bad(record, user):
            raise registry.RegistryError("not allowed")

        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with self.assertRaises(registry.RegistryError):
                eng._edit_records(self.a, [(self.pns[0], "void", good, "m1"), (self.pns[1], "void", bad, "m2")],
                                  atomic=True)
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(registry.load(self.a, self.pns[0]).status, registry.STATUS_IN_WORK)

    def test_locks_are_taken_several_at_a_time_and_a_refusal_names_its_file(self):
        with self.user("Bea"):
            eng._lock(self.b, "PN-logs/HCR-00003-001.yaml", "HCR-00003-001")
        with self.user("Alex"):
            wanted = [(f"PN-logs/{pn}.yaml", str(pn)) for pn in self.pns]
            got = eng._lock_many(self.a, wanted)
            self.assertEqual([path for path, error in got.items() if error is not None],
                             ["PN-logs/HCR-00003-001.yaml"])
            self.assertIn("already checked out by Bea", str(got["PN-logs/HCR-00003-001.yaml"]))
            self.assertEqual(len(self.locks(self.a)), COUNT)

    # -- commit style ----------------------------------------------------------
    def use_style(self, style):
        import vault_settings
        with self.user("Alex"):
            vault_settings.edit(self.a, commit_style=style)

    def test_one_commit_for_the_batch_when_the_vault_says_so(self):
        self.use_style("per_batch")
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(eng.checkin_many, self.a, self.pns, "Tweaks")
            self.assertEqual((len(done), failed), (COUNT, []))
            self.assertEqual(self.count(commands, "git commit"), 1)
            self.assertEqual(self.count(commands, "git push"), 1)
            self.assertEqual(self.locks(self.a), {})
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), f"{COUNT} parts: Tweaks")
        body = git(self.a, "log", "-1", "--format=%B")
        for pn in self.pns:
            self.assertIn(f"{pn}: Tweaks", body)
        self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_the_default_is_still_one_commit_per_part(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            _, commands = self.commands(eng.checkin_many, self.a, self.pns, "Tweaks")
        self.assertEqual(self.count(commands, "git commit"), COUNT)

    def test_a_single_part_keeps_its_own_commit_even_with_the_batch_style(self):
        self.use_style("per_batch")
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            eng.checkin_many(self.a, self.pns[:1], "Solo")
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), f"{self.pns[0]}: Solo")

    def test_more_than_a_hundred_records_still_make_one_commit(self):
        paths = []
        for n in range(150):
            path = f"PN-logs/extra{n}.yaml"
            (self.a / path).write_text("a: 1\n")
            paths.append(path)
        git(self.a, "add", "--", *paths)
        before = git(self.a, "rev-list", "--count", "HEAD")
        eng._commit_paths(self.a, "Many", "", paths)
        self.assertEqual(int(git(self.a, "rev-list", "--count", "HEAD")) - int(before), 1)
        self.assertEqual(len(git(self.a, "show", "--name-only", "--format=", "HEAD").split()), 150)

    def test_debug_mode_logs_where_the_time_went(self):
        lines = []
        with mock.patch.object(eng, "DEBUG", True), mock.patch.object(eng, "LOG", lines.append):
            with self.user("Alex"):
                eng.checkout_many(self.a, self.pns[:2])
                self.change(self.pns[:2])
                eng.checkin_many(self.a, self.pns[:2], "Timed")
        timing = [line for line in lines if line.startswith("Timing: check in on 2 part(s)")]
        self.assertEqual(len(timing), 1)
        self.assertIn("git commit x2", timing[0])
        self.assertIn("git push", timing[0])

    def test_nothing_is_logged_about_timing_when_debug_is_off(self):
        lines = []
        with mock.patch.object(eng, "DEBUG", False), mock.patch.object(eng, "LOG", lines.append):
            with self.user("Alex"):
                eng.checkout_many(self.a, self.pns[:2])
        self.assertFalse([line for line in lines if line.startswith("Timing:")])


    # -- files saved after the click -----------------------------------------------------------------------------
    def snapshot(self, pns):
        return eng.watch_files(self.a, {pn: "A" for pn in pns})

    def test_a_part_saved_after_the_click_is_refused_and_stays_checked_out(self):
        import file_snapshot
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            snap = self.snapshot(self.pns)
            (self.a / cad(self.pns[1])).write_bytes(b"saved again, after the click")
            record_before = (self.a / eng.record_relpath(self.pns[1])).read_bytes()
            (done, failed), _ = self.commands(eng.checkin_many, self.a, self.pns, "Tweaks", snapshot=snap)
            self.assertEqual([pn for pn, _r in done], [p for p in self.pns if p != self.pns[1]])
            self.assertEqual([pn for pn, _why in failed], [self.pns[1]])
            self.assertIn("changed after you pressed Check In", failed[0][1])
            self.assertIn("still checked out to you", failed[0][1])
            mine = {path for path, (who, _n) in self.locks(self.a).items() if who == "you"}
            self.assertIn(cad(self.pns[1]).lower(), mine)               # its locks are kept
            self.assertEqual(len(mine), 3)                              # and nobody else's were
            self.assertEqual((self.a / eng.record_relpath(self.pns[1])).read_bytes(), record_before)
        self.assertEqual(file_snapshot._ACTIVE, [])                     # released

    def test_the_part_can_be_checked_in_again_afterwards(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            snap = self.snapshot(self.pns[:1])
            (self.a / cad(self.pns[0])).write_bytes(b"saved after the click")
            _done, failed = eng.checkin_many(self.a, self.pns[:1], "Try 1", snapshot=snap)
            self.assertEqual(len(failed), 1)
            done, failed = eng.checkin_many(self.a, self.pns[:1], "Try 2", snapshot=self.snapshot(self.pns[:1]))
            self.assertEqual((len(done), failed), (1, []))
            self.assertEqual(self.locks(self.a), {})

    def test_a_snapshot_with_no_change_lets_everything_through(self):
        import file_snapshot
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns)
            self.change(self.pns)
            done, failed = eng.checkin_many(self.a, self.pns, "Tweaks", snapshot=self.snapshot(self.pns))
            self.assertEqual((len(done), failed), (COUNT, []))
        self.assertEqual(file_snapshot._ACTIVE, [])

    def test_save_progress_is_meant_for_working_so_a_later_save_is_fine(self):
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:2])
            snap = self.snapshot(self.pns[:2])
            (self.a / cad(self.pns[0])).write_bytes(b"kept working, saved again")
            done, failed = eng.checkin_many(self.a, self.pns[:2], "Checkpoint", keep_lock=True, snapshot=snap)
            self.assertEqual((len(done), failed), (2, []))

    def test_a_download_in_between_does_not_look_like_a_save(self):
        from vault_fixture import PART, PRT
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:2])
            self.change(self.pns[:2])
            snap = self.snapshot(self.pns[:2])
        with self.user("Bea"):                                          # somebody else uploads something
            eng.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"Bea's change")
            eng.checkin(self.b, PART, "Bea")
        with self.user("Alex"):
            before = (self.a / cad(self.pns[0])).stat().st_mtime_ns
            eng._pull(self.a)                                           # git stashes and restores Alex's edits
            self.assertNotEqual((self.a / cad(self.pns[0])).stat().st_mtime_ns, before)   # so the time did change
            done, failed = eng.checkin_many(self.a, self.pns[:2], "Tweaks", snapshot=snap)
            self.assertEqual((len(done), failed), (2, []))

    def saving_during_add(self, victim):
        """eng.run that rewrites the victim's file while 'git add' is reading it."""
        real = eng.run

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "add"] and cad(victim) in command:
                (self.a / cad(victim)).write_bytes(b"saved in the middle of the upload!")
            return real(command, repo, quiet)
        return run

    def check_save_during_add(self):
        victim = self.pns[1]
        with self.user("Alex"):
            eng.checkout_many(self.a, self.pns[:3])
            self.change(self.pns[:3])
            record_before = (self.a / eng.record_relpath(victim)).read_bytes()
            with mock.patch.object(eng, "run", self.saving_during_add(victim)):
                done, failed = eng.checkin_many(self.a, self.pns[:3], "Tweaks")
            self.assertEqual([pn for pn, _r in done], [self.pns[0], self.pns[2]])
            self.assertEqual([pn for pn, _why in failed], [victim])
            self.assertIn("was saved while Litterbox was reading it", failed[0][1])
            self.assertEqual((self.a / eng.record_relpath(victim)).read_bytes(), record_before)
            self.assertEqual(git(self.a, "diff", "--cached", "--name-only"), "")        # nothing left staged
            self.assertIn(cad(victim).lower(), self.locks(self.a))                       # still checked out
        log = self.remote_log()
        self.assertIn(f"{self.pns[0]}: Tweaks", " ".join(log) + " ".join(
            git(self.a, "log", "-3", "--format=%B").splitlines()))
        self.assertFalse(any(f"{victim}: Tweaks" in line for line in git(self.a, "log", "-5", "--format=%B").splitlines()))

    def test_a_save_in_the_middle_of_reading_is_caught_per_part(self):
        self.check_save_during_add()

    def test_a_save_in_the_middle_of_reading_is_caught_in_a_one_commit_batch(self):
        self.use_style("per_batch")
        self.check_save_during_add()


if __name__ == "__main__":
    unittest.main()
