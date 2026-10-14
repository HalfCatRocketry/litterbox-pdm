"""Tests for user/settings.py: personal settings, the log and debug mode."""

import tempfile
import unittest
from pathlib import Path
from litterbox.user import settings


class TestSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_defaults_when_no_file(self):
        self.assertEqual(settings.load(self.dir / "nope.yaml"), settings.DEFAULTS)

    def test_round_trip_creates_folders(self):
        path = self.dir / "deep" / "settings.yaml"
        self.assertTrue(settings.save({"repo": r"D:\Vaults\fsae"}, path))
        self.assertEqual(settings.load(path)["repo"], r"D:\Vaults\fsae")
        self.assertNotIn("\r", path.read_text(encoding="utf-8"))

    def test_broken_files_fall_back_to_defaults(self):
        path = self.dir / "settings.yaml"
        for text in ("just: [broken\n", "- a list\n- not a dict\n", ""):
            path.write_text(text, encoding="utf-8")
            self.assertEqual(settings.load(path), settings.DEFAULTS)

    def test_unwritable_location_does_not_crash(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        self.assertFalse(settings.save({"repo": "x"}, blocker / "settings.yaml"))
        settings.append_log("hello", blocker / "logs" / "litterbox.log")     # must not raise

    def test_log_lines_and_rotation(self):
        path = self.dir / "logs" / "litterbox.log"
        settings.append_log("first\nsecond", path)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in lines], ["first", "second"])
        old_limit = settings.MAX_LOG_BYTES
        settings.MAX_LOG_BYTES = 10
        try:
            settings.append_log("third", path)
        finally:
            settings.MAX_LOG_BYTES = old_limit
        self.assertTrue(path.with_name("litterbox.log.old").exists())
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)


class TestDebugMode(unittest.TestCase):
    def test_off_by_default_and_for_odd_values(self):
        self.assertFalse(settings.is_debug({}))
        self.assertFalse(settings.is_debug({"debug_mode": False}))
        self.assertFalse(settings.is_debug({"debug_mode": "nope"}))
        self.assertFalse(settings.is_debug({"debug_mode": 2}))
        self.assertFalse(settings.is_debug(None))
        self.assertFalse(settings.DEFAULTS["debug_mode"])

    def test_on_when_true(self):
        self.assertTrue(settings.is_debug({"debug_mode": True}))
        self.assertTrue(settings.is_debug({"debug_mode": "True"}))
        self.assertTrue(settings.is_debug({"debug_mode": "yes"}))

    def test_read_from_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.yaml"
            path.write_text("debug_mode: true\n", encoding="utf-8")
            self.assertTrue(settings.is_debug(settings.load(path)))
            self.assertFalse(settings.is_debug(settings.load(Path(d) / "missing.yaml")))


if __name__ == "__main__":
    unittest.main()
