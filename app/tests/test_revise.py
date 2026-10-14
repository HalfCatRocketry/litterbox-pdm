"""
Tests for revise.py (Revise and Cancel Revision), using a pretend SolidWorks (documents are text; each
'ref: <path>' line is one reference) and the same two-user vault as the engine tests.
They need Linux, macOS or WSL.

The important ones are the "leaves nothing behind" tests: a copy that fails, a push that fails, a race
lost to someone else, and a crash must each leave the vault exactly as it was.

Run from the app folder with:  python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from test_importer import FakeSolidWorks  # noqa: E402
from vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable  # noqa: E402

from litterbox.parts import engine as eng  # noqa: E402
from litterbox.records import registry  # noqa: E402
from litterbox.parts import revise  # noqa: E402
from litterbox.core.pn import PN  # noqa: E402

PRT_B = PRT.replace("_A.", "_B.")
DRW_B = DRW.replace("_A.", "_B.")
PRT_C = PRT.replace("_A.", "_C.")
CANCELLED_PRT = "cancelled-revs/CANCELLED_HCR-00001-001_B.SLDPRT"
CANCELLED_DRW = "cancelled-revs/CANCELLED_HCR-00001-001_B.SLDDRW"


@SKIP_ON_WINDOWS
class ReviseFixture(TwoUserVault):
    """The vault's one part (HCR-00001-001) is released at Rev A. Its drawing refers to its model."""

    def setUp(self):
        super().setUp()
        self.fake = FakeSolidWorks(self.root)
        with self.user("Alex"):
            for rel in (PRT, DRW):
                (self.a / rel).chmod(0o644)
            (self.a / PRT).write_text("model A\n", encoding="utf-8")
            (self.a / DRW).write_text(f"drawing A\nref: {self.a / PRT}\n", encoding="utf-8")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Make the files text")
            git(self.a, "push")
            eng.enforce_read_only(self.a)
            eng.release(self.a, PART)
        with self.user("Bea"):
            eng.get_latest(self.b)

    def locks(self, repo):
        with self.user("Alex" if repo == self.a else "Bea"):
            return eng.get_locks(repo, strict=True)

    def revise(self, repo=None, user="Alex", reason="Bore too small", **kwargs):
        with self.user(user):
            return revise.revise(repo or self.a, PART, reason, backend=self.fake, log=lambda *_: None, **kwargs)

    def cancel(self, repo=None, user="Alex", reason="Started by mistake", **kwargs):
        with self.user(user):
            return revise.cancel_revision(repo or self.a, PART, reason, backend=self.fake, log=lambda *_: None,
                                          **kwargs)

    def assert_untouched(self, repo):
        """Rev A is still the released, locked-by-nobody revision, with nothing new in cad and git clean."""
        record = registry.load(repo, PART)
        self.assertEqual((record.revision, record.released_revision, record.status), ("A", "A", "released"))
        self.assertEqual(sorted(p.name for p in (repo / "cad").iterdir()),
                         ["HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.SLDPRT"])
        self.assertFalse((repo / "cancelled-revs").exists())
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(self.locks(repo), {})
        self.assertFalse(revise._journal_path(repo).exists())


class TestRevise(ReviseFixture, unittest.TestCase):
    def test_plan_for_a_released_part(self):
        with self.user("Alex"):
            plan = revise.revise_plan(self.a, PART)
        self.assertTrue(plan.ok, plan.problems)
        self.assertEqual((plan.revision, plan.new_revision), ("A", "B"))
        self.assertEqual(plan.copies, [(DRW, DRW_B), (PRT, PRT_B)])

    def test_revise_copies_the_files_and_checks_the_new_revision_out(self):
        files = self.revise()
        self.assertEqual(sorted(files), [DRW_B, PRT_B])
        self.assertEqual((self.a / PRT_B).read_text(), "model A\n")
        self.assertIn(f"ref: {self.a / PRT_B}", (self.a / DRW_B).read_text())        # the drawing follows the new model
        self.assertNotIn(f"ref: {self.a / PRT}", (self.a / DRW_B).read_text())
        record = registry.load(self.a, PART)
        self.assertEqual((record.revision, record.released_revision, record.status), ("B", "A", "in_work"))
        event = record.history[-1]
        self.assertEqual((event["event"], event["revision"], event["from_revision"], event["reason"]),
                         ("revised", "B", "A", "Bore too small"))
        self.assertEqual(sorted(self.locks(self.a)), sorted([REC.lower(), PRT_B.lower(), DRW_B.lower()]))
        self.assertTrue(is_writable(self.a / PRT_B))
        self.assertFalse(is_writable(self.a / PRT))                                  # Rev A stays frozen
        self.assertEqual((self.a / PRT).read_text(), "model A\n")
        self.assertIn("HCR-00001-001: Revised to Rev B - Bore too small", self.remote_log())
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertFalse(revise._journal_path(self.a).exists())
        with self.user("Alex"):
            row = self.status_of(self.a)
        self.assertEqual((row.kind, row.revision, row.released_revision), ("mine", "B", "A"))
        self.assertEqual(row.state, "Checked out by you (Rev A released)")

    def test_everyone_else_sees_the_new_revision_as_checked_out_by_the_reviser(self):
        self.revise()
        with self.user("Bea"):
            eng.get_latest(self.b)
            row = self.status_of(self.b)
            self.assertEqual((row.kind, row.locked_by, row.revision), ("theirs", "Alex", "B"))
            self.assertEqual(row.files, [DRW_B, PRT_B])
            self.assertEqual(sorted(row.revisions), ["A", "B"])
            with self.assertRaises(eng.LitterboxError):
                eng.checkout(self.b, PART)

    def test_the_revision_can_be_worked_on_and_released_like_any_other(self):
        self.revise()
        with self.user("Alex"):
            (self.a / PRT_B).write_text("model B\n", encoding="utf-8")
            eng.checkin(self.a, PART, "Bigger bore")
            eng.release(self.a, PART)
            record = registry.load(self.a, PART)
        self.assertEqual((record.revision, record.released_revision, record.status), ("B", "B", "released"))
        self.assertEqual((self.a / PRT).read_text(), "model A\n")                    # Rev A never changed
        self.assertEqual((self.a / PRT_B).read_text(), "model B\n")

    def test_a_reason_is_required(self):
        with self.assertRaises(eng.LitterboxError):
            self.revise(reason="   ")
        self.assert_untouched(self.a)

    def test_only_a_released_part_can_be_revised(self):
        self.revise()
        with self.user("Alex"):
            plan = revise.revise_plan(self.a, PART)
        self.assertFalse(plan.ok)
        self.assertTrue(any("released" in p for p in plan.problems), plan.problems)
        with self.assertRaises(eng.LitterboxError):
            self.revise()

    def test_cots_parts_are_never_revised(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            (self.a / "cad/HCR-00002-001_A.SLDPRT").write_text("bolt\n")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "bolt")
            git(self.a, "push")
            eng.make_cots(self.a, pn)
            plan = revise.revise_plan(self.a, pn)
        self.assertFalse(plan.ok)
        self.assertTrue(any("COTS" in p for p in plan.problems), plan.problems)

    def test_the_plan_is_blocked_when_the_vault_is_ahead_or_files_clash(self):
        with self.user("Alex"):
            (self.a / "cad").mkdir(exist_ok=True)
            (self.a / PRT_B).write_text("in the way")
            plan = revise.revise_plan(self.a, PART)
        self.assertFalse(plan.ok)
        self.assertTrue(any("already exists" in p for p in plan.problems), plan.problems)

    # -- leaving nothing behind --------------------------------------------
    def test_a_failed_copy_leaves_the_vault_as_it_was(self):
        self.fake.fail_on = "HCR-00001-001_A.SLDDRW"           # the model copies, then the drawing fails
        with self.assertRaises(Exception):
            self.revise()
        self.assert_untouched(self.a)
        self.fake.fail_on = None
        self.revise()                                           # and a later attempt works
        self.assertEqual(registry.load(self.a, PART).revision, "B")

    def test_a_refused_repoint_leaves_the_vault_as_it_was(self):
        self.fake.refuse_repoint = True
        with self.assertRaises(eng.LitterboxError):
            self.revise()
        self.assert_untouched(self.a)

    def test_a_failed_push_takes_back_the_commit_and_the_files(self):
        with mock.patch.object(eng, "_push_with_retry", side_effect=eng.LitterboxError("network down")):
            with self.assertRaises(eng.LitterboxError):
                self.revise()
        self.assert_untouched(self.a)

    def test_cancelling_while_copying_leaves_nothing(self):
        real_copy = self.fake.copy

        def copy_then_stop(src, dst):
            real_copy(src, dst)
            raise KeyboardInterrupt()
        self.fake.copy = copy_then_stop
        with self.assertRaises(KeyboardInterrupt):
            self.revise()
        self.assert_untouched(self.a)

    def test_losing_the_race_to_someone_else_leaves_nothing(self):
        self.revise(repo=self.b, user="Bea")                    # Bea got there first
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.revise()                                       # Alex has not pulled yet
        self.assertIn("Bea", str(ctx.exception))
        self.assertFalse((self.a / PRT_B).exists())
        self.assertEqual({v[1] for v in self.locks(self.a).values()}, {"Bea"})
        self.assertFalse(revise._journal_path(self.a).exists())

    def test_a_crash_is_cleaned_up_from_the_note_left_behind(self):
        self.a.joinpath(PRT_B).write_text("half copied")
        revise._write_journal(self.a, {"op": "revise", "token": "tok1", "record": REC, "added": [PRT_B, DRW_B],
                                       "removed": [], "locked": []})
        with self.user("Alex"):
            self.assertEqual(revise.recover(self.a, log=lambda *_: None), "cleaned")
            self.assertEqual(revise.recover(self.a, log=lambda *_: None), "nothing")
        self.assert_untouched(self.a)

    def test_recovery_never_deletes_files_the_vault_owns(self):
        revise._write_journal(self.a, {"op": "revise", "token": "tok2", "record": REC, "added": [PRT, PRT_B],
                                       "removed": [], "locked": []})
        with self.user("Alex"):
            revise.recover(self.a, log=lambda *_: None)
        self.assertTrue((self.a / PRT).exists())                # tracked in the latest commit: left alone

    def test_a_note_that_points_outside_the_vault_is_refused(self):
        revise._write_journal(self.a, {"op": "revise", "token": "tok3", "record": REC,
                                       "added": ["../elsewhere/file"], "removed": [], "locked": []})
        with self.assertRaises(eng.LitterboxError):
            revise.recover(self.a, log=lambda *_: None)


class TestCancelRevision(ReviseFixture, unittest.TestCase):
    def test_cancel_keeps_the_work_in_cancelled_revs_and_returns_to_the_released_revision(self):
        self.revise()
        with self.user("Alex"):
            (self.a / PRT_B).write_text("unsaved edits\n", encoding="utf-8")            # work that must not be lost
            plan = revise.cancel_revision_plan(self.a, PART)
            self.assertTrue(plan.ok, plan.problems)
            self.assertEqual((plan.revision, plan.back_to), ("B", "A"))
        kept = self.cancel()
        self.assertEqual(sorted(kept), [CANCELLED_DRW, CANCELLED_PRT])
        self.assertEqual((self.a / CANCELLED_PRT).read_text(), "unsaved edits\n")
        self.assertIn(f"ref: {self.a / CANCELLED_PRT}", (self.a / CANCELLED_DRW).read_text())
        self.assertFalse((self.a / PRT_B).exists())
        self.assertFalse((self.a / DRW_B).exists())
        record = registry.load(self.a, PART)
        self.assertEqual((record.revision, record.released_revision, record.status), ("A", "A", "released"))
        event = record.history[-1]
        self.assertEqual((event["event"], event["cancelled"], event["reason"]),
                         ("revision_cancelled", "B", "Started by mistake"))
        self.assertEqual(registry.cancelled_revisions(record), ["B"])
        self.assertIn("HCR-00001-001: Cancelled Rev B - Started by mistake", self.remote_log())
        self.assertEqual(self.locks(self.a), {})
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        with self.user("Alex"):
            self.assertEqual(self.status_of(self.a).kind, "released")
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertFalse((self.b / PRT_B).exists())
            self.assertTrue((self.b / CANCELLED_PRT).exists())

    def test_a_cancelled_letter_is_never_used_again(self):
        self.revise()
        self.cancel()
        files = self.revise(reason="Second try")
        self.assertEqual(sorted(files), [DRW.replace("_A.", "_C."), PRT_C])
        self.assertEqual(registry.load(self.a, PART).revision, "C")

    def test_someone_else_can_cancel_a_revision_nobody_is_holding(self):
        self.revise()
        with self.user("Alex"):
            eng.checkin(self.a, PART, "Save", allow_unchanged=True)         # Alex lets go of it
        with self.user("Bea"):
            eng.get_latest(self.b)
        self.cancel(repo=self.b, user="Bea")
        self.assertEqual(registry.load(self.b, PART).revision, "A")
        self.assertTrue((self.b / CANCELLED_PRT).exists())

    def test_it_is_refused_while_someone_else_has_the_revision_checked_out(self):
        self.revise()
        with self.user("Bea"):
            eng.get_latest(self.b)
            plan = revise.cancel_revision_plan(self.b, PART)
            self.assertFalse(plan.ok)
            self.assertTrue(any("Alex" in p for p in plan.problems), plan.problems)
            with self.assertRaises(eng.LitterboxError):
                revise.cancel_revision(self.b, PART, "No", backend=self.fake, log=lambda *_: None)
        self.assertTrue((self.a / PRT_B).exists())
        self.assertEqual(registry.load(self.a, PART).revision, "B")

    def test_a_part_that_was_never_released_uses_void_instead(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            plan = revise.cancel_revision_plan(self.a, pn)
        self.assertFalse(plan.ok)
        self.assertTrue(any("Void" in p for p in plan.problems), plan.problems)

    def test_a_reason_is_required(self):
        self.revise()
        with self.assertRaises(eng.LitterboxError):
            self.cancel(reason=" ")
        self.assertTrue((self.a / PRT_B).exists())

    def test_a_failed_cancel_puts_everything_back(self):
        self.revise()
        with self.user("Alex"):
            (self.a / PRT_B).write_text("my edits\n", encoding="utf-8")
        with mock.patch.object(eng, "_push_with_retry", side_effect=eng.LitterboxError("network down")):
            with self.assertRaises(eng.LitterboxError):
                self.cancel()
        record = registry.load(self.a, PART)
        self.assertEqual((record.revision, record.status), ("B", "in_work"))
        self.assertTrue((self.a / PRT_B).exists())
        self.assertTrue((self.a / DRW_B).exists())
        self.assertFalse((self.a / "cancelled-revs").exists())
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertFalse(revise._journal_path(self.a).exists())
        self.assertEqual(self.locks(self.a), {})               # nobody is left holding half a lock

    def test_a_failed_copy_while_cancelling_changes_nothing(self):
        self.revise()
        self.fake.fail_on = "HCR-00001-001_B.SLDDRW"
        with self.assertRaises(Exception):
            self.cancel()
        self.assertTrue((self.a / PRT_B).exists())
        self.assertFalse((self.a / "cancelled-revs").exists())
        self.assertEqual(registry.load(self.a, PART).revision, "B")


class TestRulesAroundRevisions(ReviseFixture, unittest.TestCase):
    def test_a_part_with_a_released_revision_cannot_be_voided_or_made_cots(self):
        self.revise()
        with self.user("Alex"):
            eng.checkin(self.a, PART, "Save", allow_unchanged=True)
            with self.assertRaises(eng.LitterboxError) as ctx:
                eng.void(self.a, PART, "No longer needed")
            self.assertIn("Cancel Revision", str(ctx.exception))
            plan = eng.make_cots_plan(self.a, PART)
            self.assertFalse(plan.ok)
            self.assertTrue(any("revised" in p for p in plan.problems), plan.problems)

    def test_a_never_released_part_can_still_be_voided(self):
        pn = self.add_created_part(2)
        with self.user("Alex"):
            eng.void(self.a, pn, "Never needed")
            self.assertEqual(self.status_of(self.a, pn).kind, "void")


if __name__ == "__main__":
    unittest.main()
