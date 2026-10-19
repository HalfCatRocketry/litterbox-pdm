"""
Tests for Add org... (vault_clone.py and the planning in gui_logic): reading a repository URL, and really cloning one.
"""

import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path


from litterbox.gui.logic import org_menu
from litterbox.vault import clone as vault_clone
from litterbox.errors import LitterboxError
from litterbox import diagnostics
from tests.support.gui_source import gui_source
from tests.support.vault_fixture import DRW, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault
from litterbox.git import lfs_download


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ParsingTheUrl(unittest.TestCase):
    def test_the_usual_hosts(self):
        cases = {
            "https://dev.azure.com/halfcat/Rockets/_git/hcr-litterbox": "hcr-litterbox",
            "https://halfcat@dev.azure.com/halfcat/Rockets/_git/hcr-litterbox": "hcr-litterbox",
            "https://github.com/HalfCatRocketry/litterbox-pdm.git": "litterbox-pdm",
            "https://github.com/HalfCatRocketry/litterbox-pdm.git/": "litterbox-pdm",
            "  https://gitlab.com/team/vault  ": "vault",
            "git@github.com:team/my-vault.git": "my-vault",
            "ssh://git@host/team/vault.git": "vault",
            "https://dev.azure.com/o/p/_git/My%20Vault": "My Vault",
            "https://host/team/repo?ref=main": "repo",
        }
        for url, name in cases.items():
            self.assertEqual(vault_clone.parse_url(url), (name, ""), url)

    def test_things_that_are_not_urls_are_explained(self):
        for text in ("", "   ", "hcr-litterbox", "C:\\Litterbox\\hcr", "https://has a space/repo", "https://"):
            name, problem = vault_clone.parse_url(text)
            self.assertEqual(name, "", text)
            self.assertTrue(problem, text)

    def test_characters_windows_cannot_have_in_a_folder_name_are_replaced(self):
        name, problem = vault_clone.parse_url("https://host/team/we%3Aird%2Aname")
        self.assertEqual((name, problem), ("we_ird_name", ""))


class Planning(unittest.TestCase):
    def test_the_folder_is_inside_the_root(self):
        target, problem = org_menu.plan_add_org("https://h/t/hcr-litterbox", "/root/Litterbox", {})
        self.assertEqual((target, problem), (Path("/root/Litterbox/hcr-litterbox"), ""))

    def test_a_vault_that_is_already_added_is_not_cloned_again(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "hcr-litterbox").mkdir()
            target, problem = org_menu.plan_add_org("https://h/t/hcr-litterbox", root,
                                                 {"HCR": str(Path(root) / "hcr-litterbox")})
        self.assertIsNone(target)
        self.assertIn("HCR is already added", problem)

    def test_an_added_vault_whose_folder_is_gone_is_cloned_again(self):
        with tempfile.TemporaryDirectory() as root:          # a real folder: /root can't be looked in when not root
            gone = Path(root) / "hcr-litterbox"
            target, problem = org_menu.plan_add_org("https://h/t/hcr-litterbox", root, {"HCR": str(gone)})
        self.assertEqual((target, problem), (gone, ""))

    def test_a_folder_that_cant_be_looked_in_is_explained_not_raised(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "hcr-litterbox"
            with mock.patch.object(Path, "exists", side_effect=PermissionError(13, "Permission denied")):
                target, problem = org_menu.plan_add_org("https://h/t/hcr-litterbox", root, {"HCR": str(folder)})
        self.assertIsNone(target)
        self.assertIn("isn't allowed to look in", problem)
        self.assertIn("Permission denied", problem)

    def test_a_bad_url_gives_its_reason(self):
        target, problem = org_menu.plan_add_org("nonsense", "/root/Litterbox", {})
        self.assertIsNone(target)
        self.assertIn("repository URL", problem)


class Cloning(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.remote = self.root / "remote.git"
        git(self.root, "init", "--bare", "-b", "main", str(self.remote))
        work = self.root / "work"
        git(self.root, "clone", str(self.remote), str(work))
        (work / ".litterbox").mkdir()
        (work / ".litterbox" / "config.yaml").write_text("org: HCR\n")
        git(work, "-c", "user.name=T", "-c", "user.email=t@x", "add", ".")
        git(work, "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-m", "vault")
        git(work, "push", "origin", "HEAD:main")
        self.url = self.remote.as_uri()
        self.lines = []
        old = diagnostics.LOG
        diagnostics.LOG = self.lines.append
        self.addCleanup(setattr, diagnostics, "LOG", old)

    def test_a_clone_lands_in_the_target_and_is_a_vault(self):
        target = self.root / "Litterbox" / "remote"                    # parent folder does not exist yet
        self.assertEqual(vault_clone.clone(self.url, target, on_demand=False), target)
        self.assertEqual(org_menu.inspect_vault_folder(target), ("HCR", ""))
        self.assertTrue(any("git clone" in line for line in self.lines))

    def test_create_new_vault_uses_an_earlier_tries_copy_but_nothing_else(self):
        target = self.root / "Litterbox" / "remote"
        vault_clone.clone_or_reuse(self.url, target, on_demand=False)
        (target / "left from the first try").write_text("x")
        self.assertEqual(vault_clone.clone_or_reuse(self.url, target, on_demand=False), target)    # not cloned again
        self.assertTrue((target / "left from the first try").exists())
        other = self.root / "Litterbox" / "other"
        other.mkdir()
        (other / "notes.txt").write_text("mine")
        with self.assertRaises(LitterboxError) as caught:
            vault_clone.clone_or_reuse(self.url, other, on_demand=False)
        self.assertIn("isn't a copy of", str(caught.exception))
        empty = self.root / "Litterbox" / "empty"
        empty.mkdir()
        self.assertEqual(vault_clone.clone_or_reuse(self.url, empty, on_demand=False), empty)    # an empty folder is fine
        self.assertTrue((empty / ".git").exists())

    def test_a_failed_clone_says_why(self):
        with self.assertRaises(LitterboxError) as caught:
            vault_clone.clone((self.root / "nothing-here.git").as_uri(), self.root / "x", on_demand=False)
        self.assertIn("Could not clone", str(caught.exception))

    def test_an_empty_repository_clones_but_is_not_a_vault_yet(self):
        empty = self.root / "empty.git"
        git(self.root, "init", "--bare", "-b", "main", str(empty))
        target = vault_clone.clone(empty.as_uri(), self.root / "empty", on_demand=False)
        org, problem = org_menu.inspect_vault_folder(target)
        self.assertEqual(org, "")
        self.assertIn("Create new org", problem)


class Wiring(unittest.TestCase):
    def test_add_org_asks_for_a_url_and_clones_in_the_background(self):
        source = gui_source()
        for text in ("class CloneDialog", "CloneDialog(self, settings.ROOT).show()", "vault_clone.clone(url.strip(), target, settings.downloads_on_demand(self.settings))",
                     'label="Cloning the vault', "self.add_org()"):
            self.assertIn(text, source)
        self.assertNotIn("self._org_setup(None)", source)


@SKIP_ON_WINDOWS
class CloningOnDemand(TwoUserVault, unittest.TestCase):
    """Add org... with download on demand: the new copy has every record but no CAD files yet."""
    LFS = True

    def test_the_new_copy_has_pointers_and_downloads_on_demand(self):
        target = self.root / "Litterbox" / "fresh"
        with self.user("Cy"):
            vault_clone.clone(self.remote.as_uri(), target)
        self.assertEqual(lfs_download.stubs(target, [PRT, DRW]), [PRT, DRW])
        self.assertTrue(lfs_download.is_on_demand(target))
        self.assertTrue((target / REC).is_file())                              # the records are all there

    def test_without_on_demand_everything_is_downloaded(self):
        target = self.root / "Litterbox" / "full"
        vault_clone.clone(self.remote.as_uri(), target, on_demand=False)
        self.assertEqual(lfs_download.stubs(target, [PRT, DRW]), [])
        self.assertEqual((target / PRT).read_bytes(), b"version 1")



if __name__ == "__main__":
    unittest.main()
