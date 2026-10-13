"""
Tests for Add org... (vault_clone.py and the planning in gui_logic): reading a repository URL, and really cloning one.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import gui_logic as logic  # noqa: E402
import litterbox_engine as eng  # noqa: E402
import vault_clone  # noqa: E402


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
        target, problem = logic.plan_add_org("https://h/t/hcr-litterbox", "/root/Litterbox", {})
        self.assertEqual((target, problem), (Path("/root/Litterbox/hcr-litterbox"), ""))

    def test_a_vault_that_is_already_added_is_not_cloned_again(self):
        target, problem = logic.plan_add_org("https://h/t/hcr-litterbox", "/root/Litterbox",
                                             {"HCR": "/root/Litterbox/hcr-litterbox"})
        self.assertIsNone(target)
        self.assertIn("HCR is already added", problem)

    def test_a_bad_url_gives_its_reason(self):
        target, problem = logic.plan_add_org("nonsense", "/root/Litterbox", {})
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
        old = eng.LOG
        eng.LOG = self.lines.append
        self.addCleanup(setattr, eng, "LOG", old)

    def test_a_clone_lands_in_the_target_and_is_a_vault(self):
        target = self.root / "Litterbox" / "remote"                    # parent folder does not exist yet
        self.assertEqual(vault_clone.clone(self.url, target), target)
        self.assertEqual(logic.inspect_vault_folder(target), ("HCR", ""))
        self.assertTrue(any("git clone" in line for line in self.lines))

    def test_a_failed_clone_says_why(self):
        with self.assertRaises(eng.LitterboxError) as caught:
            vault_clone.clone((self.root / "nothing-here.git").as_uri(), self.root / "x")
        self.assertIn("Could not clone", str(caught.exception))

    def test_an_empty_repository_clones_but_is_not_a_vault_yet(self):
        empty = self.root / "empty.git"
        git(self.root, "init", "--bare", "-b", "main", str(empty))
        target = vault_clone.clone(empty.as_uri(), self.root / "empty")
        org, problem = logic.inspect_vault_folder(target)
        self.assertEqual(org, "")
        self.assertIn("Create new vault", problem)


class Wiring(unittest.TestCase):
    def test_add_org_asks_for_a_url_and_clones_in_the_background(self):
        source = (Path(__file__).resolve().parent.parent / "litterbox_gui.py").read_text(encoding="utf-8")
        for text in ("class CloneDialog", "CloneDialog(self, settings.ROOT).show()", "vault_clone.clone(url.strip(), target)",
                     'label="Cloning the vault', "self.add_org()"):
            self.assertIn(text, source)
        self.assertNotIn("self._org_setup(None)", source)


if __name__ == "__main__":
    unittest.main()
