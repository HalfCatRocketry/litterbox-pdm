"""Tests that a creation that fails leaves nothing behind, and the New Part command line. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import PART, PRT, SKIP_ON_WINDOWS, git, is_writable
from litterbox.parts import create
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import runner
from tests.support.create_fixture import CreateFixture


@SKIP_ON_WINDOWS
class CreateFailures(CreateFixture, unittest.TestCase):
    def test_a_push_that_always_fails_leaves_nothing_behind(self):
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        commits = len(self.remote_log())
        with self.user("Alex"):
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "Doomed")
            self.assertIn(f"{create.ATTEMPTS} tries", str(ctx.exception))
            self.assertIn("simulated network failure", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
            self.assertEqual(create.new_part(self.a, "Works now"), PN("HCR", 2, 1))   # the number is still free
        self.assertEqual(len(self.remote_log()), commits + 1)

    def test_offline_at_the_start_changes_nothing(self):
        real_run = runner.run

        def offline(command, repo, quiet=False):
            if command[:2] == ["git", "fetch"]:
                raise LitterboxError("simulated: could not resolve host")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", offline):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "No network")
            self.assertIn("online", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_connection_lost_after_a_failed_push_changes_nothing(self):
        real_run = runner.run
        fetches = {"count": 0}

        def flaky(command, repo, quiet=False):
            if command[:2] == ["git", "fetch"]:
                fetches["count"] += 1
                if fetches["count"] > 1:                      # the first pull works, then the network drops
                    raise LitterboxError("simulated: could not resolve host")
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated: connection reset")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", flaky):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "Lost connection")
            self.assertIn("Are you online?", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_a_checked_out_part_is_not_disturbed_by_a_creation(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            pn = create.new_part(self.a, "Another part")
            self.assertEqual(pn, PN("HCR", 2, 1))
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")      # edit still there
            self.assertEqual(len(self.locks(self.a)), 3)                              # still checked out
            self.assertTrue(is_writable(self.a / PRT))
            self.assertEqual(git(self.remote, "show", f"main:{PRT}"), "version 1")     # edit was not uploaded
            self.assertEqual(sum(1 for line in self.remote_log() if "Created" in line), 1)
            self.assertTrue(checkin.checkin(self.a, PART, "Finished my edit").uploaded)   # and it can still be checked in

    def test_a_failed_push_does_not_disturb_a_checked_out_part_either(self):
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(create.CreateError):
                    create.new_part(self.a, "Doomed")
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    def test_a_created_part_can_be_checked_out_and_given_files(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Rear upright")
            self.assertEqual(checkout.checkout(self.a, pn).files, [])
            prt = "cad/HCR-00002-001_A.SLDPRT"
            (self.a / prt).write_bytes(b"brand new part")
            self.assertEqual(checkin.checkin(self.a, pn, "First version").files, [prt])
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.status_of(self.a, pn).state, "Available")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual((self.b / prt).read_bytes(), b"brand new part")

    def test_command_line(self):
        with self.user("Alex"):
            code, out = self.run_cli("part", "From the command line")
            self.assertEqual(code, 0)
            self.assertIn("Created HCR-00002-001", out)
            code, out = self.run_cli("variant", "1", "Right hand", "--variant", "4")
            self.assertEqual(code, 0)
            self.assertIn("Created HCR-00001-004", out)
            code, out = self.run_cli("variants", "1")
            self.assertIn("HCR-00001-004", out)
            self.assertIn("Next free variant: 002", out)
            code, out = self.run_cli("next")
            self.assertIn("Next free part number: 00003", out)
            code, out = self.run_cli("part", "Duplicate", "--number", "1", "--variant", "1")
            self.assertEqual(code, 1)
            self.assertIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
