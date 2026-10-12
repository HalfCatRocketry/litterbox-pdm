"""
Tests for the vault settings (config.get_commit_style / set_values, vault_settings.edit) and the Admin dialog's
wiring. Alex is the Owner; Bea is a Member. They need Linux, macOS or WSL.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from vault_fixture import SKIP_ON_WINDOWS, git  # noqa: E402
from test_workflow import Fixture  # noqa: E402

import config  # noqa: E402
import litterbox_engine as eng  # noqa: E402
import people  # noqa: E402
import vault_settings  # noqa: E402


class ConfigValues(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)

    def test_the_default_is_one_commit_per_part(self):
        self.assertEqual(config.get_commit_style(self.repo), "per_part")

    def test_setting_and_clearing_it(self):
        config.set_values(self.repo, commit_style="per_batch")
        self.assertEqual(config.get_commit_style(self.repo), "per_batch")
        config.set_values(self.repo, commit_style="per_part")
        self.assertEqual(config.get_commit_style(self.repo), "per_part")

    def test_bad_values_are_refused(self):
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, commit_style="sometimes")
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, colour="red")

    def test_a_hand_edited_bad_value_is_reported(self):
        (self.repo / config.CONFIG_DIR).mkdir()
        (self.repo / config.CONFIG_DIR / config.CONFIG_FILE).write_text("commit_style: nonsense\n")
        with self.assertRaises(config.ConfigError):
            config.get_commit_style(self.repo)


@SKIP_ON_WINDOWS
class EditingTheSetting(Fixture, unittest.TestCase):
    def test_an_admin_changes_it_for_everyone(self):
        with self.user("Alex"):
            self.assertTrue(vault_settings.edit(self.a, commit_style="per_batch"))
            self.assertEqual(self.locks(self.a), {})
        self.assertIn("Vault settings: commit_style = per_batch", self.remote_log()[0])
        self.get_latest("Bea")
        self.assertEqual(config.get_commit_style(self.b), "per_batch")

    def test_saying_the_same_thing_again_changes_nothing(self):
        with self.user("Alex"):
            self.assertFalse(vault_settings.edit(self.a, commit_style="per_part"))

    def test_a_member_may_not(self):
        with self.user("Bea"):
            with self.assertRaises(eng.LitterboxError):
                vault_settings.edit(self.b, commit_style="per_batch")
        self.assertEqual(config.get_commit_style(self.b), "per_part")

    def test_a_failed_upload_puts_everything_back(self):
        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with mock.patch.object(eng, "_push_with_retry", side_effect=eng.LitterboxError("no network")):
                with self.assertRaises(eng.LitterboxError):
                    vault_settings.edit(self.a, commit_style="per_batch")
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)
            self.assertEqual(config.get_commit_style(self.a), "per_part")
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})

    def test_manage_settings_is_an_admin_action(self):
        self.assertIn("manage_settings", people.ADMIN_ACTIONS)


class Wiring(unittest.TestCase):
    def test_the_team_window_and_app_are_wired_to_the_dialog(self):
        source = (Path(__file__).resolve().parent.parent / "litterbox_gui.py").read_text(encoding="utf-8")
        self.assertIn('"Vault Settings..."', source)
        self.assertIn("def edit_vault_settings", source)
        self.assertIn("vault_settings.edit(repo, commit_style=style)", source)
        self.assertEqual(source.count('allows("manage_settings")'), 1)


if __name__ == "__main__":
    unittest.main()
