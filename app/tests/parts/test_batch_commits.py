"""Tests for how many commits a batch makes (commit_style) and the debug-mode timing. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, git
from litterbox import diagnostics
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.git import committing
from tests.support.batch_fixture import BatchFixture, COUNT


@SKIP_ON_WINDOWS
class BatchCommits(BatchFixture, unittest.TestCase):
    def test_one_commit_for_the_batch_when_the_vault_says_so(self):
        self.use_style("per_batch")
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            (done, failed), commands = self.commands(checkin.checkin_many, self.a, self.pns, "Tweaks")
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
            checkout.checkout_many(self.a, self.pns)
            self.change(self.pns)
            _, commands = self.commands(checkin.checkin_many, self.a, self.pns, "Tweaks")
        self.assertEqual(self.count(commands, "git commit"), COUNT)

    def test_a_single_part_keeps_its_own_commit_even_with_the_batch_style(self):
        self.use_style("per_batch")
        with self.user("Alex"):
            checkout.checkout_many(self.a, self.pns[:1])
            self.change(self.pns[:1])
            checkin.checkin_many(self.a, self.pns[:1], "Solo")
        self.assertEqual(git(self.a, "log", "-1", "--format=%s"), f"{self.pns[0]}: Solo")

    def test_more_than_a_hundred_records_still_make_one_commit(self):
        paths = []
        for n in range(150):
            path = f"PN-logs/extra{n}.yaml"
            (self.a / path).write_text("a: 1\n")
            paths.append(path)
        git(self.a, "add", "--", *paths)
        before = git(self.a, "rev-list", "--count", "HEAD")
        committing.commit_paths(self.a, "Many", "", paths)
        self.assertEqual(int(git(self.a, "rev-list", "--count", "HEAD")) - int(before), 1)
        self.assertEqual(len(git(self.a, "show", "--name-only", "--format=", "HEAD").split()), 150)

    def test_debug_mode_logs_where_the_time_went(self):
        lines = []
        with mock.patch.object(diagnostics, "DEBUG", True), mock.patch.object(diagnostics, "LOG", lines.append):
            with self.user("Alex"):
                checkout.checkout_many(self.a, self.pns[:2])
                self.change(self.pns[:2])
                checkin.checkin_many(self.a, self.pns[:2], "Timed")
        timing = [line for line in lines if line.startswith("Timing: check in on 2 part(s)")]
        self.assertEqual(len(timing), 1)
        self.assertIn("git commit x2", timing[0])
        self.assertIn("git push", timing[0])

    def test_nothing_is_logged_about_timing_when_debug_is_off(self):
        lines = []
        with mock.patch.object(diagnostics, "DEBUG", False), mock.patch.object(diagnostics, "LOG", lines.append):
            with self.user("Alex"):
                checkout.checkout_many(self.a, self.pns[:2])
        self.assertFalse([line for line in lines if line.startswith("Timing:")])


if __name__ == "__main__":
    unittest.main()
