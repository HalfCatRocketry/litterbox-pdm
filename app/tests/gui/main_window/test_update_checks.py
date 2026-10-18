"""Tests for the update check at start-up. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes


class UpdateWiring(unittest.TestCase):
    """The window side of updates: asking, downloading, handing over to the installer."""

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.updater = self.gui.updater             # the copy the window itself uses
        self.update = self.updater.Update("0.2.0", "Fixes things.", "Litterbox-Setup-0.2.0.exe", "https://x", "a" * 64, 5)
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.said, self.tasks, self.scheduled = [], [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, on_success))
        app.after = lambda ms, fn=None: self.scheduled.append((ms, fn))
        app.queue = __import__("queue").Queue()
        app.settings = {}
        app.destroy = self.destroy = lambda: None
        self.app = app

    def test_nothing_happens_without_an_update(self):
        self.app._offer_update(None)
        self.assertEqual(self.box.calls, [])

    def test_yes_downloads_and_no_does_not(self):
        self.box.answer = False
        self.app._offer_update(self.update)
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        self.app._offer_update(self.update)
        self.assertEqual(len(self.tasks), 1)
        question = self.box.calls[-1][1][1]
        self.assertIn("0.2.0", question)
        self.assertIn("Fixes things.", question)

    def test_a_download_problem_becomes_a_plain_error(self):
        from litterbox.errors import LitterboxError
        self.app.install_update(self.update)
        work, _ = self.tasks[0]
        original = self.updater.download
        self.updater.download = lambda update: (_ for _ in ()).throw(self.updater.UpdateError("did not match"))
        try:
            with self.assertRaisesRegex(LitterboxError, "did not match"):
                work()
        finally:
            self.updater.download = original

    def test_after_downloading_the_installer_starts_and_litterbox_closes(self):
        started = []
        original = self.updater.launch_installer
        self.updater.launch_installer = lambda path: started.append(path)
        try:
            self.app._run_installer("C:/tmp/Setup.exe")
        finally:
            self.updater.launch_installer = original
        self.assertEqual(started, ["C:/tmp/Setup.exe"])
        self.assertIs(self.scheduled[-1][1], self.destroy)

    def test_if_the_installer_cannot_start_litterbox_stays_open(self):
        original = self.updater.launch_installer
        self.updater.launch_installer = lambda path: (_ for _ in ()).throw(self.updater.UpdateError("blocked"))
        try:
            self.app._run_installer("C:/tmp/Setup.exe")
        finally:
            self.updater.launch_installer = original
        self.assertEqual(self.scheduled, [])
        self.assertEqual(self.box.calls[-1][0], "showerror")

    def test_a_source_copy_never_checks_and_explains_when_asked(self):
        original = self.updater.find_update
        self.updater.find_update = lambda *a, **k: self.fail("a development copy must not look for updates")
        try:
            self.app._start_update_check()
            self.app.check_for_updates()
        finally:
            self.updater.find_update = original
        self.assertEqual(self.tasks, [])
        self.assertIn("source files", self.box.calls[-1][1][1])

    def test_the_setting_can_switch_the_check_off(self):
        settings = self.gui.settings
        self.assertTrue(settings.update_check_enabled({}))
        self.assertTrue(settings.update_check_enabled({"update_check": True}))
        for off in (False, "false", "No", "off"):
            self.assertFalse(settings.update_check_enabled({"update_check": off}), off)


if __name__ == "__main__":
    unittest.main()
