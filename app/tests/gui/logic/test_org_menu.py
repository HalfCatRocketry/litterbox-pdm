"""Tests for gui/logic/org_menu.py: the org box, Add org and Create new vault."""

import unittest
from pathlib import Path
from litterbox.gui.logic import org_menu
from tests.support.gui_source import gui_source


class TestOrgs(unittest.TestCase):
    def test_known_orgs_ignores_junk(self):
        self.assertEqual(org_menu.known_orgs({}), {})
        self.assertEqual(org_menu.known_orgs({"orgs": ["x"]}), {})
        self.assertEqual(org_menu.known_orgs({"orgs": {"hcr": "C:/a", "SAE": "C:/b", "": "c"}}),
                         {"HCR": "C:/a", "SAE": "C:/b"})

    def test_old_single_repo_settings_migrate(self):
        data = {"repo": "C:/v"}
        self.assertTrue(org_menu.migrate_settings(data, lambda folder: "HCR"))
        self.assertEqual(org_menu.known_orgs(data), {"HCR": "C:/v"})
        self.assertEqual(org_menu.current_org(data), "HCR")
        self.assertFalse(org_menu.migrate_settings(data, lambda folder: "XXX"))     # already migrated
        self.assertFalse(org_menu.migrate_settings({"repo": "C:/v"}, lambda folder: None))
        self.assertFalse(org_menu.migrate_settings({}, lambda folder: "HCR"))

    def test_opens_the_last_org_worked_on(self):
        data = {}
        org_menu.remember_org(data, "hcr", "C:/a")
        org_menu.remember_org(data, "SAE", "C:/b")
        self.assertEqual(org_menu.current_org(data), "SAE")
        data["last_org"] = "HCR"
        self.assertEqual(org_menu.current_org(data), "HCR")
        data["last_org"] = "GONE"
        self.assertEqual(org_menu.current_org(data), "HCR")           # falls back to the first
        self.assertIsNone(org_menu.current_org({}))

    def test_menu_lists_orgs_then_actions(self):
        data = {}
        org_menu.remember_org(data, "HCR", "C:/a")
        org_menu.remember_org(data, "SAE", "C:/b")
        self.assertEqual(org_menu.org_menu_values(data), ["HCR", "SAE", org_menu.ADD_ORG, org_menu.CREATE_VAULT, org_menu.EDIT_ORG])


class TestVaultCreatedText(unittest.TestCase):
    def result(self, **changes):
        from types import SimpleNamespace
        base = dict(org="HCR", pushed=True, owner=SimpleNamespace(name="Alex Smith"), team_error="", warnings=[])
        base.update(changes)
        return SimpleNamespace(**base)

    def test_a_complete_set_up(self):
        text = org_menu.vault_created_text(self.result())
        self.assertIn("The HCR vault is set up and uploaded.", text)
        self.assertIn("Alex Smith is the team's Owner.", text)

    def test_team_trouble_is_explained_and_not_fatal(self):
        text = org_menu.vault_created_text(self.result(owner=None, team_error="The host didn't answer."))
        self.assertIn("Use Team... to set it up later", text)
        self.assertIn("didn't answer", text)

    def test_local_only_and_warnings(self):
        text = org_menu.vault_created_text(self.result(pushed=False, warnings=["Mind the gap."]))
        self.assertIn("on this computer only", text)
        self.assertIn("Mind the gap.", text)


class InspectVaultFolder(unittest.TestCase):
    """Add org... reads the org from a vault that already exists instead of asking for it."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = Path(self.dir.name)

    def vault(self, config_text=None, git=True):
        if git:
            (self.folder / ".git").mkdir()
        if config_text is not None:
            (self.folder / ".litterbox").mkdir()
            (self.folder / ".litterbox" / "config.yaml").write_text(config_text)

    def test_a_vault_gives_its_org(self):
        self.vault("org: HCR\n")
        self.assertEqual(org_menu.inspect_vault_folder(self.folder), ("HCR", ""))

    def test_a_missing_folder_or_a_plain_folder_is_explained(self):
        org, problem = org_menu.inspect_vault_folder(self.folder / "nope")
        self.assertEqual((org, problem), ("", "That folder doesn't exist."))
        self.vault(git=False)
        org, problem = org_menu.inspect_vault_folder(self.folder)
        self.assertEqual(org, "")
        self.assertIn("isn't a git repository", problem)

    def test_an_empty_repository_points_to_create_new_vault(self):
        self.vault()
        org, problem = org_menu.inspect_vault_folder(self.folder)
        self.assertEqual(org, "")
        self.assertIn("Create new vault", problem)

    def test_a_bad_config_is_reported(self):
        self.vault("org: TOOLONGCODE\n")
        org, problem = org_menu.inspect_vault_folder(self.folder)
        self.assertEqual(org, "")
        self.assertIn("org code", problem)


class AddOrgWiring(unittest.TestCase):
    def test_add_org_no_longer_opens_the_org_setup_dialog(self):
        source = gui_source()
        self.assertIn("self.add_org()", source)
        self.assertNotIn("self._org_setup(None)", source)
        self.assertIn("part_number.NEW_VAULT_BASE_DIGITS", source)

    def test_new_vaults_suggest_six_digits_but_existing_vaults_keep_their_default(self):
        from litterbox.core import part_number
        self.assertEqual(part_number.NEW_VAULT_BASE_DIGITS, 6)
        self.assertEqual(part_number.DEFAULT_BASE_DIGITS, 5)


if __name__ == "__main__":
    unittest.main()
