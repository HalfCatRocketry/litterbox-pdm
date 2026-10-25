"""Tests for the org's SolidWorks version: the rules (cad/solidworks_versions.py), the vault setting, the check the
actions make (permission_check.check_solidworks_version) and the warning before Check Out. No git."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from litterbox import version
from litterbox.cad import solidworks_versions as versions
from litterbox.cad.solidworks import sw_process
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.gui.logic import team_text
from litterbox.parts import permission_check
from litterbox.vault import config
from litterbox.vault import config_write
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace


def installed(test, major):
    """Pretend this computer has SolidWorks of this major version (None: none)."""
    replace(test, sw_process, "installed_major_version", lambda: major)


class Rules(unittest.TestCase):
    def test_majors_are_shown_as_years(self):
        self.assertEqual(versions.year_of_major(32), 2024)
        self.assertIsNone(versions.year_of_major(None))
        installed(self, 29)
        self.assertEqual(versions.installed_year(), 2021)

    def test_comparing(self):
        self.assertEqual(versions.compare(2024, 2025), versions.NEWER)
        self.assertEqual(versions.compare(2024, 2022), versions.OLDER)
        self.assertEqual(versions.compare(2024, 2024), versions.OK)
        self.assertEqual(versions.compare(None, 2025), versions.OK)            # no version chosen
        self.assertEqual(versions.compare(2024, None), versions.OK)            # no SolidWorks here

    def test_words(self):
        text = versions.blocked_text(2024, 2025, "check out HCR-00042-001")
        self.assertTrue(text.startswith("Litterbox won't check out HCR-00042-001: your SolidWorks is 2025"))
        self.assertIn("Team > Vault Settings", text)
        self.assertIn("older than this org's SolidWorks 2024", versions.older_text(2024, 2022))
        prompt = team_text.solidworks_version_prompt(2024, 2025)
        self.assertIn("that includes you", prompt)
        self.assertIn(f"Litterbox {version.VERSION} or newer", prompt)
        self.assertNotIn("includes you", team_text.solidworks_version_prompt(2024, 2024))

    def test_the_years_offered(self):
        self.assertEqual(versions.year_choices(2026)[:2], [2027, 2026])
        self.assertEqual(versions.year_choices(2026)[-1], versions.CHOICES_FROM)
        self.assertEqual(versions.year_choices(2026, 2012)[-1], 2012)            # the vault's own is always there


class Vault(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)

    def written(self):
        return yaml.safe_load(config.config_path(self.repo).read_text(encoding="utf-8"))

    def test_setting_it_needs_this_litterbox_and_clearing_it_removes_the_line(self):
        self.assertIsNone(config.get_solidworks_version(self.repo))
        config_write.set_values(self.repo, solidworks_version=2024)
        self.assertEqual(config.get_solidworks_version(self.repo), 2024)
        self.assertEqual(self.written()["min_litterbox_version"], version.release())
        config_write.set_values(self.repo, solidworks_version=None)
        self.assertNotIn("solidworks_version", self.written())
        self.assertIsNone(config.get_solidworks_version(self.repo))

    def test_bad_values_are_refused(self):
        for bad in ("2024", 24, True, 1999):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                config_write.set_values(self.repo, solidworks_version=bad)
        config.config_path(self.repo).parent.mkdir(parents=True, exist_ok=True)
        config.config_path(self.repo).write_text("solidworks_version: twenty\n", encoding="utf-8")
        with self.assertRaisesRegex(config.ConfigError, "solidworks_version in"):
            config.get_solidworks_version(self.repo)

    def test_a_newer_solidworks_is_stopped_and_an_older_one_or_none_is_not(self):
        permission_check.check_solidworks_version(self.repo, "check out it")      # nothing set: always fine
        config_write.set_values(self.repo, solidworks_version=2024)
        installed(self, 33)
        with self.assertRaisesRegex(LitterboxError, "won't check out it: your SolidWorks is 2025"):
            permission_check.check_solidworks_version(self.repo, "check out it")
        for major in (32, 30, None):
            installed(self, major)
            permission_check.check_solidworks_version(self.repo, "check out it")


class CheckOutWarning(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        config_write.set_values(self.repo, solidworks_version=2024)
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: self.repo
        app._plan = lambda action: SimpleNamespace(targets=[PN("HCR", 7, 1)])
        self.ran = []
        app._run_batch = lambda action, plan, work: self.ran.append(action)
        self.app = app

    def asked(self):
        return [call for call in self.box.calls if call[0] == "askokcancel"]

    def test_an_older_solidworks_is_warned_about_once(self):
        installed(self, 30)
        self.app.check_out()
        self.assertIn("older than this org's SolidWorks 2024", self.asked()[0][1][1])
        self.app.check_out()
        self.assertEqual((len(self.asked()), self.ran), (1, ["checkout", "checkout"]))

    def test_saying_cancel_checks_nothing_out(self):
        installed(self, 30)
        self.box.answer = False
        self.app.check_out()
        self.assertEqual(self.ran, [])

    def test_the_same_or_no_solidworks_asks_nothing(self):
        for major in (32, None):
            installed(self, major)
            self.app.check_out()
        self.assertEqual((self.asked(), self.ran), ([], ["checkout", "checkout"]))


class SettingsWindow(unittest.TestCase):
    def test_the_vault_settings_window_offers_the_version_and_returns_it(self):
        gui = load_gui_with_fakes(FakeBox())
        dialog_class = gui.vault_settings_dialog.VaultSettingsDialog
        parent = SimpleNamespace(winfo_rootx=lambda: 0, winfo_rooty=lambda: 0, winfo_width=lambda: 800,
                                 winfo_height=lambda: 600)
        current = {"commit_style": "per_part", "release_rule": "warn", "require_signatures": False,
                   "assembly_variant_start": 500, "solidworks_version": 2012}
        dialog = dialog_class(parent, current, installed=2024)
        self.assertEqual(dialog.version_var.get(), "SolidWorks 2012")             # kept, though it is old
        self.assertEqual(list(dialog.versions)[0], gui.vault_settings_dialog.ANY_VERSION)
        dialog.destroy = lambda: None
        dialog.version_var.set(gui.vault_settings_dialog.ANY_VERSION)
        dialog._ok()
        self.assertIsNone(dialog.result["solidworks_version"])


if __name__ == "__main__":
    unittest.main()
