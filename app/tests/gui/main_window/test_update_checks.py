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

    def found(self, **fields):
        return self.updater.Found(**fields)

    def keep_saves(self):
        """settings.save stands in for writing C:\\Litterbox\\settings.yaml: it notes what would be saved."""
        saved, original = [], self.gui.settings.save
        self.gui.settings.save = lambda data, path=None: saved.append(dict(data)) or True
        self.addCleanup(setattr, self.gui.settings, "save", original)
        self.app._log = lambda text: self.said.append(text)
        return saved

    def test_what_a_check_learned_is_saved_and_the_update_offered(self):
        saved = self.keep_saves()
        self.box.answer = False
        self.app._update_found(self.found(update=self.update, revoked=("k1",), moved_to="new/place"))
        self.assertEqual(saved[-1]["revoked_update_keys"], ["k1"])
        self.assertEqual(saved[-1]["update_repo"], "new/place")
        self.assertIn("new/place", self.box.calls[0][1][1])                 # asked: says where updates come from
        self.assertEqual(self.box.calls[-1][0], "askyesno")                  # then offers the update

    def test_a_quiet_check_only_logs_its_problem(self):
        saved = self.keep_saves()
        self.app._update_found(self.found(problem="offline"), quiet=True)
        self.assertEqual((self.box.calls, saved), ([], []))
        self.assertIn("Update check: offline", self.said)
        self.app._update_found(self.found(problem="offline"))
        self.assertEqual(self.box.calls[-1][0], "showwarning")

    def test_get_beta_versions_switches_the_channel_after_asking(self):
        saved = self.keep_saves()
        self.box.answer = False
        self.app.toggle_beta_versions()
        self.assertEqual(saved, [])
        self.box.answer = True
        self.app.toggle_beta_versions()
        self.assertEqual(self.app.settings["update_channel"], "beta")
        self.app.toggle_beta_versions()
        self.assertNotIn("update_channel", self.app.settings)
        self.assertEqual(len(saved), 2)

    def test_the_setting_can_switch_the_check_off(self):
        settings = self.gui.settings
        self.assertTrue(settings.update_check_enabled({}))
        self.assertTrue(settings.update_check_enabled({"update_check": True}))
        for off in (False, "false", "No", "off"):
            self.assertFalse(settings.update_check_enabled({"update_check": off}), off)


if __name__ == "__main__":
    unittest.main()
