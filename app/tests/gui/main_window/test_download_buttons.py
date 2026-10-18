"""Tests for Download All and for applying your download setting to a vault. The window itself is replaced by
stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look."""

import unittest

from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace

from litterbox.errors import LitterboxError


class DownloadButtons(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: "C:/vault"
        self.tasks = []
        app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, done, kw))
        self.app = app
        self.calls = []
        replace(self, self.gui.downloads, "download_all", lambda repo: self.calls.append(("all", repo)))

    def test_download_all_asks_first_then_runs_in_the_background(self):
        self.app.download_all()
        work, done, kw = self.tasks[0]
        self.assertEqual(kw["label"], "Downloading everything")
        work()
        self.assertEqual(self.calls, [("all", "C:/vault")])
        self.assertTrue(any(call[0] == "askyesno" for call in self.box.calls))

    def test_saying_no_downloads_nothing(self):
        self.box.answer = False
        self.app.download_all()
        self.assertEqual(self.tasks, [])

    def test_the_setting_is_applied_once_per_vault(self):
        applied = []
        replace(self, self.gui.downloads, "apply_mode", lambda repo, on_demand: applied.append((repo, on_demand)))
        for _ in range(3):
            self.app._use_download_setting("C:/vault", True)
        self.app._use_download_setting("C:/other", False)
        self.assertEqual(applied, [("C:/vault", True), ("C:/other", False)])

    def test_a_problem_applying_it_is_logged_not_raised(self):
        lines = []
        replace(self, self.gui.diagnostics, "LOG", lines.append)

        def broken(repo, on_demand):
            raise LitterboxError("git-lfs is not installed")
        replace(self, self.gui.downloads, "apply_mode", broken)
        self.app._use_download_setting("C:/vault", True)
        self.assertIn("could not set how this vault downloads", lines[0])


if __name__ == "__main__":
    unittest.main()
