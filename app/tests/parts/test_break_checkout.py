"""Tests for Break Checkout (parts/break_checkout.py) and for keeping the person's work safe afterwards
(git/remote.py: set_aside_broken_checkouts). Alex is the Owner; Bea is a Member. They need Linux, macOS or WSL and
are skipped on Windows."""

import unittest

from tests.support.vault_fixture import PART, PRT, REC, SKIP_ON_WINDOWS, git
from tests.support.workflow_fixture import Fixture

from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.parts import break_checkout
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.records import record_store


@SKIP_ON_WINDOWS
class BreakCheckout(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        remote.take_recovered()                                 # nothing left over from another test
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
            (self.b / PRT).write_bytes(b"bea's work")

    def test_an_admin_breaks_it_and_the_history_says_so(self):
        with self.user("Alex"):
            self.assertEqual(break_checkout.break_checkout(self.a, PART, "  Bea is away \n"), ["Bea"])
            self.assertEqual(self.locks(self.a), {})
            event = record_store.load(self.a, PART).history[-1]
        self.assertEqual((event["event"], event["by"], event["of"], event["reason"]),
                         ("checkout_broken", "Alex Smith", "Bea", "Bea is away"))
        self.assertIn("Checkout by Bea broken - Bea is away", self.remote_log()[0])
        with self.user("Alex"):
            checkout.checkout(self.a, PART)                     # anyone can check it out now
            self.assertEqual(self.status_of(self.a).kind, "mine")

    def test_a_member_may_not_and_a_reason_is_needed(self):
        with self.user("Bea"):
            with self.assertRaises(LitterboxError):
                break_checkout.break_checkout(self.b, PART, "mine now")
        with self.user("Alex"):
            with self.assertRaises(LitterboxError) as caught:
                break_checkout.break_checkout(self.a, PART, "   ")
            self.assertIn("Say why", str(caught.exception))
        self.assertTrue(self.locks(self.a))                     # still Bea's

    def test_only_someone_elses_checkout_can_be_broken(self):
        with self.user("Bea"):
            checkin.checkin(self.b, PART, "done")
        with self.user("Alex"):
            with self.assertRaises(LitterboxError) as caught:
                break_checkout.break_checkout(self.a, PART, "why not")
            self.assertIn("Nobody else has", str(caught.exception))
            checkout.checkout(self.a, PART)
            with self.assertRaises(LitterboxError):
                break_checkout.break_checkout(self.a, PART, "my own")     # yours: use Undo Checkout

    def test_the_persons_work_is_kept_when_someone_else_changes_the_part_afterwards(self):
        with self.user("Alex"):
            break_checkout.break_checkout(self.a, PART, "Bea is away")
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"alex's work")
            checkin.checkin(self.a, PART, "Alex's change")
        with self.user("Bea"):
            get_latest.get_latest(self.b)                       # would stop (or stash Bea's work) without the guard
            self.assertEqual((self.b / PRT).read_bytes(), b"alex's work")
            [(folder, files)] = remote.take_recovered()
            self.assertEqual(files, [PRT])
            self.assertEqual((folder / PRT).read_bytes(), b"bea's work")
            self.assertEqual(folder.parent.name, f"{self.b.name}-recovered")      # beside the vault, not in it
            self.assertEqual(git(self.b, "status", "--porcelain"), "")
            self.assertEqual(git(self.b, "stash", "list"), "")
            self.assertEqual(record_store.load(self.b, PART).history[-1]["event"], "checked_in")
            self.assertEqual(self.status_of(self.b).kind, "ok")

    def test_a_record_alone_is_just_put_back_and_unchanged_files_are_left_alone(self):
        with self.user("Alex"):
            break_checkout.break_checkout(self.a, PART, "Bea is away")
        with self.user("Bea"):
            self.assertIn(REC.lower(), {line.split()[-1].lower() for line in git(self.b, "status", "--porcelain").splitlines()})
            get_latest.get_latest(self.b)
            self.assertEqual(remote.take_recovered(), [])       # the CAD file didn't change in the vault: kept as it is
            self.assertEqual((self.b / PRT).read_bytes(), b"bea's work")
            self.assertEqual(record_store.load(self.b, PART).history[-1]["event"], "checkout_broken")
            self.assertEqual(self.status_of(self.b).kind, "unclaimed")       # Bea's changes, not checked out
            checkout.checkout(self.b, PART)                     # and Bea can carry on with them
            self.assertEqual((self.b / PRT).read_bytes(), b"bea's work")
            checkin.checkin(self.b, PART, "finished after all")


if __name__ == "__main__":
    unittest.main()
