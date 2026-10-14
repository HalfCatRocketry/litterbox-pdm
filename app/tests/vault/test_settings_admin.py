"""
Tests for the vault settings (config.get_commit_style / set_values, vault_settings.edit) and the Admin dialog's
wiring. Alex is the Owner; Bea is a Member. They need Linux, macOS or WSL.
"""

import unittest
from pathlib import Path
from unittest import mock

from tests.support.vault_fixture import SKIP_ON_WINDOWS, git
from tests.support.workflow_fixture import Fixture

from litterbox.vault import config
from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox.vault import settings_admin as vault_settings
from litterbox.errors import LitterboxError
from litterbox import layout


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

    def test_the_release_rule_and_signatures_can_be_set_and_cleared(self):
        config.set_values(self.repo, release_rule="block", require_signatures=True)
        self.assertEqual(config.get_release_rule(self.repo), "block")
        self.assertTrue(config.get_require_signatures(self.repo))
        config.set_values(self.repo, release_rule="warn", require_signatures=False)
        self.assertEqual(config.get_release_rule(self.repo), "warn")
        self.assertFalse(config.get_require_signatures(self.repo))
        self.assertEqual(config.load(self.repo), {})

    def test_other_lines_in_the_file_survive_a_change(self):
        config.set_values(self.repo, commit_style="per_batch")
        text = (self.repo / layout.CONFIG_DIR / layout.CONFIG_FILE).read_text()
        (self.repo / layout.CONFIG_DIR / layout.CONFIG_FILE).write_text(text + "org: HCR\n")
        config.set_values(self.repo, release_rule="off")
        self.assertEqual(config.load(self.repo), {"commit_style": "per_batch", "org": "HCR", "release_rule": "off"})

    def test_bad_rule_and_signature_values_are_refused(self):
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, release_rule="maybe")
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, require_signatures="yes")

    def test_bad_values_are_refused(self):
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, commit_style="sometimes")
        with self.assertRaises(config.ConfigError):
            config.set_values(self.repo, colour="red")

    def test_a_hand_edited_bad_value_is_reported(self):
        (self.repo / layout.CONFIG_DIR).mkdir()
        (self.repo / layout.CONFIG_DIR / layout.CONFIG_FILE).write_text("commit_style: nonsense\n")
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
            with self.assertRaises(LitterboxError):
                vault_settings.edit(self.b, commit_style="per_batch")
        self.assertEqual(config.get_commit_style(self.b), "per_part")

    def test_a_failed_upload_puts_everything_back(self):
        before = git(self.a, "rev-parse", "HEAD")
        with self.user("Alex"):
            with mock.patch.object(eng, "_push_with_retry", side_effect=LitterboxError("no network")):
                with self.assertRaises(LitterboxError):
                    vault_settings.edit(self.a, commit_style="per_batch")
            self.assertEqual(git(self.a, "rev-parse", "HEAD"), before)
            self.assertEqual(config.get_commit_style(self.a), "per_part")
            self.assertEqual(git(self.a, "status", "--porcelain"), "")
            self.assertEqual(self.locks(self.a), {})

    def test_several_settings_go_up_in_one_commit(self):
        before = int(git(self.a, "rev-list", "--count", "HEAD"))
        with self.user("Alex"):
            vault_settings.edit(self.a, commit_style="per_batch", release_rule="block")
            self.assertEqual(config.get_release_rule(self.a), "block")
        self.assertEqual(int(git(self.a, "rev-list", "--count", "HEAD")), before + 1)
        self.get_latest("Bea")
        self.assertEqual(config.get_release_rule(self.b), "block")

    def test_manage_settings_is_an_admin_action(self):
        self.assertIn("manage_settings", people.ADMIN_ACTIONS)


class DialogLogic(unittest.TestCase):
    def test_only_what_changed_is_saved(self):
        from litterbox.gui.logic import gui_logic as logic
        current = {"commit_style": "per_part", "release_rule": "warn", "require_signatures": False}
        self.assertEqual(logic.changed_settings(current, dict(current)), {})
        self.assertEqual(logic.changed_settings(current, None), {})
        self.assertEqual(logic.changed_settings(current, dict(current, release_rule="block", require_signatures=True)),
                         {"release_rule": "block", "require_signatures": True})


class Wiring(unittest.TestCase):
    def test_the_team_window_and_app_are_wired_to_the_dialog(self):
        source = (Path(__file__).resolve().parents[2] / "litterbox" / "gui" / "litterbox_gui.py").read_text(encoding="utf-8")
        self.assertIn('"Vault Settings..."', source)
        self.assertIn("def edit_vault_settings", source)
        self.assertIn("vault_settings.edit(repo, **changes)", source)
        for key in ("commit_style", "release_rule", "require_signatures"):
            self.assertIn(f'("{key}",', source)
        self.assertEqual(source.count('allows("manage_settings")'), 1)


if __name__ == "__main__":
    unittest.main()
