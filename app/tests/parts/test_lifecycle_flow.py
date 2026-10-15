"""Tests for Release, Make COTS, Unrelease, Void and Edit Details (parts/lifecycle.py, planning.py, part_details.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import os
import unittest
from unittest import mock
from tests.support.vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, git, is_writable
from litterbox.records import record_store
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import part_changes
from litterbox.parts import part_details
from litterbox.parts import planning
from litterbox.git import runner
from litterbox.parts import undoing
from tests.support.engine_fixture import EngineFixture


@SKIP_ON_WINDOWS
class LifecycleFlow(EngineFixture, unittest.TestCase):
    def test_release_and_reopen_cycle(self):
        with self.user("Alex"):
            plan = planning.release_plan(self.a, PART)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(plan.files, [DRW, PRT])
            self.assertEqual(lifecycle.release(self.a, PART), [DRW, PRT])
            self.assertEqual(record_store.load(self.a, PART).status, "released")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Released", self.remote_log())
            self.assertFalse(is_writable(self.a / REC))
            self.assertEqual(self.status_of(self.a).kind, "released")
            with self.assertRaises(LitterboxError):
                checkout.checkout(self.a, PART)                   # released parts can't be checked out
            self.assertEqual(self.locks(self.a), {})
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(self.status_of(self.b).kind, "released")
            with self.assertRaises(LitterboxError):      # reason is required, and nothing is left behind
                lifecycle.reopen(self.b, PART, "  ")
            self.assertEqual(self.locks(self.b), {})
            lifecycle.reopen(self.b, PART, "Bore diameter wrong")
            record = record_store.load(self.b, PART)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(record.history[-1]["reason"], "Bore diameter wrong")
            self.assertIn("HCR-00001-001: Unreleased - Bore diameter wrong", self.remote_log())
            checkout.checkout(self.b, PART)                       # editable again

    def test_release_is_blocked_while_checked_out_or_changed(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half done")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            plan = planning.release_plan(self.b, PART)
            self.assertFalse(plan.ok)
            self.assertTrue(any("checked out by Alex" in p for p in plan.problems), plan.problems)
            with self.assertRaises(LitterboxError):
                lifecycle.release(self.b, PART)
        with self.user("Alex"):
            plan = planning.release_plan(self.a, PART)
            self.assertTrue(any("not checked in" in p for p in plan.problems), plan.problems)

    def test_release_is_blocked_when_behind_the_vault(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"version 2")
            checkin.checkin(self.a, PART, "Changed")
        with self.user("Bea"):                               # Bea has not pulled
            plan = planning.release_plan(self.b, PART)
            self.assertTrue(any("Get Latest" in p for p in plan.problems), plan.problems)

    def test_make_cots_freezes_checkout_and_logs_it(self):
        with self.user("Alex"):
            plan = planning.make_cots_plan(self.a, PART)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(lifecycle.make_cots(self.a, PART), [DRW, PRT])
            record = record_store.load(self.a, PART)
            self.assertTrue(record.cots)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(record.history[-1]["event"], "made_cots")
            self.assertEqual(self.locks(self.a), {})
            self.assertIn("HCR-00001-001: Made COTS", self.remote_log())
            row = self.status_of(self.a)
            self.assertEqual((row.kind, row.cots), ("cots", True))
            with self.assertRaises(LitterboxError):
                checkout.checkout(self.a, PART)                   # a COTS part can't be checked out
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(planning.make_cots_plan(self.a, PART).ok)     # and can't be made COTS twice
            self.assertFalse(planning.release_plan(self.a, PART).ok)       # nor released
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(self.status_of(self.b).kind, "cots")

    def test_make_cots_is_blocked_while_checked_out_changed_or_behind(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half done")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            plan = planning.make_cots_plan(self.b, PART)
            self.assertTrue(any("checked out by Alex" in p for p in plan.problems), plan.problems)
            with self.assertRaises(LitterboxError):
                lifecycle.make_cots(self.b, PART)
            self.assertFalse(record_store.load(self.b, PART).cots)
        with self.user("Alex"):
            self.assertTrue(any("not checked in" in p for p in planning.make_cots_plan(self.a, PART).problems))
            checkin.checkin(self.a, PART, "Changed")
        with self.user("Bea"):                               # Bea has not pulled
            self.assertTrue(any("Get Latest" in p for p in planning.make_cots_plan(self.b, PART).problems))

    def test_make_cots_needs_cad_files_and_released_parts_are_refused(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            self.assertFalse(planning.make_cots_plan(self.a, pn).ok)
            lifecycle.release(self.a, PART)
            plan = planning.make_cots_plan(self.a, PART)
            self.assertTrue(any("released" in p for p in plan.problems), plan.problems)

    def test_reopen_undoes_make_cots(self):
        with self.user("Alex"):
            lifecycle.make_cots(self.a, PART)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            with self.assertRaises(LitterboxError):
                lifecycle.reopen(self.b, PART, " ")
            lifecycle.reopen(self.b, PART, "Not a purchased part")
            self.assertFalse(record_store.load(self.b, PART).cots)
            self.assertEqual(self.status_of(self.b).kind, "ok")
            self.assertIn("HCR-00001-001: Unreleased - Not a purchased part", self.remote_log())
            checkout.checkout(self.b, PART)

    def test_a_working_revision_next_to_a_released_one(self):
        pn = self.put_revisions(2, working="B", released="A")
        with self.user("Alex"):
            row = self.status_of(self.a, pn)
            self.assertEqual((row.revision, row.released_revision), ("B", "A"))
            self.assertEqual(row.files, ["cad/HCR-00002-001_B.SLDPRT"])
            self.assertEqual(sorted(row.revisions), ["A", "B"])
            self.assertEqual((row.kind, row.state), ("ok", "Available (Rev A released)"))
            result = checkout.checkout(self.a, pn)
            self.assertEqual(result.files, ["cad/HCR-00002-001_B.SLDPRT"])
            self.assertIn("cad/hcr-00002-001_b.sldprt", self.locks(self.a))
            self.assertNotIn("cad/hcr-00002-001_a.sldprt", self.locks(self.a))      # the released revision is never locked
            self.assertTrue(is_writable(self.a / "cad/HCR-00002-001_B.SLDPRT"))
            self.assertFalse(is_writable(self.a / "cad/HCR-00002-001_A.SLDPRT"))
            self.assertEqual(self.status_of(self.a, pn).state, "Checked out by you (Rev A released)")

    def test_releasing_the_working_revision_records_it(self):
        pn = self.put_revisions(2, working="B", released="A")
        with self.user("Alex"):
            plan = planning.release_plan(self.a, pn)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual(plan.files, ["cad/HCR-00002-001_B.SLDPRT"])
            lifecycle.release(self.a, pn)
            record = record_store.load(self.a, pn)
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
            with self.assertRaises(LitterboxError):
                part_details.edit_details(self.a, PART, "New name", "")           # not checked out
            checkout.checkout(self.a, PART)
            self.assertFalse(part_details.edit_details(self.a, PART, record_store.load(self.a, PART).name,
                                              record_store.load(self.a, PART).description))
            self.assertTrue(part_details.edit_details(self.a, PART, "Renamed part", "A description"))
            row = self.status_of(self.a)
            self.assertEqual((row.name, row.description), ("Renamed part", "A description"))
            self.assertTrue(part_changes.change_report(self.a, PART).record_edited)   # even with no CAD changes
            checkin.checkin(self.a, PART, "Fixed the name")
            self.assertIn("HCR-00001-001: Fixed the name", self.remote_log())
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            record = record_store.load(self.b, PART)
            self.assertEqual((record.name, record.description), ("Renamed part", "A description"))
            self.assertIn("edited", [e["event"] for e in record.history])
            with self.assertRaises(LitterboxError):                       # Alex no longer holds it
                part_details.edit_details(self.b, PART, "Bea's name", "")

    def test_undo_checkout_throws_away_edited_details(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            original = record_store.load(self.a, PART).name
            part_details.edit_details(self.a, PART, "Oops", "")
            undoing.undo_checkout(self.a, PART)
            self.assertEqual(record_store.load(self.a, PART).name, original)

    def test_cots_part_can_still_be_voided(self):
        with self.user("Alex"):
            lifecycle.make_cots(self.a, PART)
            lifecycle.void(self.a, PART, "Wrong part")
            self.assertEqual(self.status_of(self.a).kind, "void")

    def test_release_needs_cad_files(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            plan = planning.release_plan(self.a, pn)
            self.assertFalse(plan.ok)

    def test_void_keeps_number_and_blocks_checkout(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            lifecycle.void(self.a, pn, "Never needed")
            self.assertEqual(self.status_of(self.a, pn).kind, "void")
            self.assertIn(2, record_store.used_bases(self.a))
            with self.assertRaises(LitterboxError):
                checkout.checkout(self.a, pn)
            self.assertEqual(self.locks(self.a), {})

    def test_failed_push_during_release_restores_the_record(self):
        real_run = runner.run

        def failing(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", failing):
                with self.assertRaises(LitterboxError):
                    lifecycle.release(self.a, PART)
            record = record_store.load(self.a, PART)
            self.assertEqual(record.status, "in_work")
            self.assertEqual(len(record.history), 1)
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    def test_missing_git_name(self):
        with self.user("Alex"):
            git(self.a, "config", "user.name", "")
            with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}):
                with self.assertRaises(LitterboxError) as ctx:
                    checkout.checkout(self.a, PART)
            self.assertIn("user.name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
