"""Tests for init_vault.py: turning an empty cloned repository into a vault."""

import fnmatch
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from litterbox.vault import config
from litterbox.parts import create
from litterbox.cli import init_vault as cli_init_vault
from litterbox.vault import create_vault
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.core import part_number
from litterbox.records import record_store
from tests.support.vault_fixture import SHIM, SKIP_ON_WINDOWS, git
from litterbox.errors import LitterboxError
from litterbox.parts import part_status


class EmptyRepo(unittest.TestCase):
    """A bare 'host' repository and an empty clone of it, with a fake Git LFS."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.root = root
        bin_dir = root / "bin"
        bin_dir.mkdir()
        shutil.copy(SHIM, bin_dir / "git-lfs")
        (bin_dir / "git-lfs").chmod(0o755)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        os.environ["LFS_STORE"] = str(root / "locks.json")
        os.environ["LFS_USER"] = "alexsmith"
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
        empty = root / "empty-gitconfig"
        empty.write_text("")
        os.environ["GIT_CONFIG_GLOBAL"] = str(empty)
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        self.addCleanup(part_number.configure)               # a test that changes the digits must not leak them

        git(root, "init", "--bare", "-b", "main", "remote.git")
        self.remote = root / "remote.git"
        git(root, "clone", str(self.remote), "vault")
        self.vault = root / "vault"
        git(self.vault, "symbolic-ref", "HEAD", "refs/heads/main")
        git(self.vault, "config", "user.name", "Alex Smith")
        git(self.vault, "config", "user.email", "alex@example.com")

    def remote_files(self):
        return git(self.remote, "ls-tree", "-r", "--name-only", "main").splitlines()


@SKIP_ON_WINDOWS
class CreatingAVault(EmptyRepo):
    def make(self, **options):
        options.setdefault("set_up_team", False)
        return create_vault.create(self.vault, "hcr", **options)

    def test_writes_commits_and_pushes_the_vault_files(self):
        result = self.make()
        self.assertEqual(result.org, "HCR")
        self.assertTrue(result.pushed)
        files = self.remote_files()
        for name in (".gitattributes", ".gitignore", ".litterbox/config.yaml", "README.md"):
            self.assertIn(name, files)
        self.assertEqual(git(self.remote, "log", "--format=%s", "main"), "Litterbox: set up the HCR vault")
        self.assertEqual(git(self.vault, "status", "--porcelain"), "")

    def test_the_config_has_the_chosen_numbers_and_the_version_stamp(self):
        self.make(start_number=10001, base_digits=6, variant_digits=2)
        data = config.load(self.vault)
        self.assertEqual((data["org"], data["start_number"], data["pn_base_digits"], data["pn_variant_digits"]),
                         ("HCR", 10001, 6, 2))
        self.assertEqual(data["format_version"], 1)
        self.assertIn("min_litterbox_version", data)
        self.assertEqual(config.get_digits(self.vault), (6, 2))
        self.assertNotIn("org_name", data)

    def test_the_org_name_is_written_when_given(self):
        self.make(org_name="Hidden Creek Robotics")
        self.assertEqual(config.get_org_name(self.vault), "Hidden Creek Robotics")

    def test_gitattributes_makes_cad_lockable_lfs_files(self):
        self.make()
        text = (self.vault / ".gitattributes").read_text()
        for line in create_vault.ATTRIBUTE_LINES:
            self.assertIn(line, text.splitlines())
        self.assertNotIn("\r", text)
        self.assertIn(".tmp-*", (self.vault / ".gitignore").read_text().splitlines())

    def test_gitattributes_patterns_match_any_capitals(self):
        lfs, lockable = {}, {}
        for line in create_vault.ATTRIBUTE_LINES:
            pattern, *attributes = line.split()
            lfs[pattern], lockable[pattern] = "filter=lfs" in attributes, "lockable" in attributes

        def matches(name, attributes):
            return any(attributes[p] for p in attributes if fnmatch.fnmatchcase(name, p))

        for name in ("HCR-00042-001_A.STEP", "x.step", "x.Stp", "x.PDF", "x.pdf", "x.SldPrt", "x.x_t", "x.X_T"):
            self.assertTrue(matches(name, lfs) and matches(name, lockable), name)
        for name in ("photo.JPG", "photo.jpg", "list.XLSX"):
            self.assertTrue(matches(name, lfs) and not matches(name, lockable), name)
        self.assertFalse(matches("README.md", lfs))

    def test_the_new_vault_works_for_real_part_creation(self):
        self.make(start_number=100)
        pn = create.new_part(str(self.vault), "Front upright")
        self.assertEqual(str(pn), "HCR-00100-001")
        self.assertTrue(record_store.list_pns(self.vault))
        rows = part_status.get_status(str(self.vault))
        self.assertEqual([str(r.pn) for r in rows], ["HCR-00100-001"])

    def test_existing_ignore_and_attribute_files_only_gain_missing_lines(self):
        (self.vault / ".gitignore").write_text("build/\n*.bak\n")
        (self.vault / ".gitattributes").write_text("* text=auto\n")
        (self.vault / "README.md").write_text("Mine\n")
        git(self.vault, "add", ".")
        git(self.vault, "commit", "-m", "Initial")
        git(self.vault, "push", "-u", "origin", "main")
        self.make()
        ignore = (self.vault / ".gitignore").read_text().splitlines()
        self.assertEqual(ignore[:2], ["build/", "*.bak"])
        self.assertEqual(ignore.count("*.bak"), 1)
        self.assertIn("~$*", ignore)
        self.assertTrue((self.vault / ".gitattributes").read_text().startswith("* text=auto\n"))
        self.assertEqual((self.vault / "README.md").read_text(), "Mine\n")

    def test_no_push_leaves_it_committed_locally(self):
        result = self.make(push=False)
        self.assertFalse(result.pushed)
        self.assertEqual(self.remote_files(), []) if _remote_has_main(self.remote) else None
        self.assertEqual(git(self.vault, "log", "--format=%s"), "Litterbox: set up the HCR vault")

    def test_setting_up_the_team_makes_you_the_owner(self):
        result = self.make(set_up_team=True)
        self.assertEqual(result.owner.access, team_model.OWNER)
        self.assertEqual(result.owner.host_names, ["alexsmith"])
        self.assertEqual(result.team_error, "")
        self.assertIn(".litterbox/people.yaml", self.remote_files())

    def test_a_team_that_cannot_be_set_up_does_not_undo_the_vault(self):
        real = team_setup.setup_team

        def broken(*args, **kwargs):
            raise team_model.PeopleError("The host didn't answer.")
        team_setup.setup_team = broken
        self.addCleanup(setattr, team_setup, "setup_team", real)
        result = self.make(set_up_team=True)
        self.assertIsNone(result.owner)
        self.assertIn("didn't answer", result.team_error)
        self.assertIn(".litterbox/config.yaml", self.remote_files())

    def test_warnings_come_back_with_the_result(self):
        result = self.make(base_digits=3)
        self.assertTrue(any("only 999" in w for w in result.warnings))


def _remote_has_main(remote):
    return subprocess.run(["git", "rev-parse", "--verify", "-q", "main"], cwd=remote,
                          capture_output=True).returncode == 0


@SKIP_ON_WINDOWS
class WhenSomethingFails(EmptyRepo):
    def test_a_failed_upload_leaves_nothing_behind(self):
        (self.vault / ".gitignore").write_text("build/\n")
        git(self.vault, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        with self.assertRaises(LitterboxError):
            create_vault.create(self.vault, "HCR", set_up_team=False)
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".git", ".gitignore"])
        self.assertEqual((self.vault / ".gitignore").read_text(), "build/\n")
        self.assertFalse(_has_head(self.vault))
        git(self.vault, "remote", "set-url", "origin", str(self.remote))      # and trying again works
        create_vault.create(self.vault, "HCR", set_up_team=False)
        self.assertIn(".litterbox/config.yaml", self.remote_files())

    def test_a_failed_upload_after_earlier_commits_undoes_only_ours(self):
        (self.vault / "notes.txt").write_text("hello\n")
        git(self.vault, "add", ".")
        git(self.vault, "commit", "-m", "Initial")
        before = git(self.vault, "rev-parse", "HEAD")
        git(self.vault, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        with self.assertRaises(LitterboxError):
            create_vault.create(self.vault, "HCR", set_up_team=False)
        self.assertEqual(git(self.vault, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.vault, "status", "--porcelain"), "")
        self.assertFalse((self.vault / ".litterbox").exists())

    def test_refuses_an_existing_vault(self):
        create_vault.create(self.vault, "HCR", set_up_team=False)
        with self.assertRaises(create_vault.InitError) as caught:
            create_vault.create(self.vault, "HCR", set_up_team=False)
        self.assertIn("already looks like a vault", str(caught.exception))


def _has_head(repo):
    return subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo, capture_output=True).returncode == 0


@SKIP_ON_WINDOWS
class Planning(EmptyRepo):
    def problems(self, *args, **kwargs):
        return create_vault.plan(self.vault, *args, **kwargs).problems

    def test_a_good_setup_has_no_problems_and_changes_nothing(self):
        checked = create_vault.plan(self.vault, "HCR")
        self.assertTrue(checked.ok)
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".git"])

    def test_bad_org_codes(self):
        self.assertTrue(self.problems("H"))
        self.assertTrue(self.problems("HCRXX"))
        self.assertTrue(self.problems("H1R"))

    def test_bad_numbers(self):
        self.assertTrue(self.problems("HCR", base_digits=0))
        self.assertTrue(self.problems("HCR", base_digits=10))
        self.assertTrue(self.problems("HCR", variant_digits=5))
        self.assertTrue(self.problems("HCR", start_number=0))
        self.assertTrue(self.problems("HCR", start_number=100000, base_digits=5))
        self.assertTrue(self.problems("HCR", start_number=True))

    def test_digit_warnings(self):
        self.assertEqual(create_vault.plan(self.vault, "HCR").warnings, [])
        self.assertTrue(any("only 999" in w for w in create_vault.plan(self.vault, "HCR", base_digits=3).warnings))
        self.assertTrue(any("only 9 variants" in w for w in create_vault.plan(self.vault, "HCR", variant_digits=1).warnings))
        self.assertTrue(any("long part numbers" in w for w in create_vault.plan(self.vault, "HCR", base_digits=8).warnings))
        self.assertEqual(create_vault.plan(self.vault, "HCR", start_number=99500).warnings, [])     # numbers loop round, so a high start is fine

    def test_folder_that_is_not_a_repository(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertIn("isn't a Git repository", create_vault.plan(plain, "HCR").problems[0])
        self.assertIn("doesn't exist", create_vault.plan(self.root / "missing", "HCR").problems[0])

    def test_a_folder_inside_a_repository(self):
        inner = self.vault / "sub"
        inner.mkdir()
        self.assertIn("not the top", create_vault.plan(inner, "HCR").problems[0])

    def test_no_remote(self):
        git(self.vault, "remote", "remove", "origin")
        self.assertTrue(any("no remote" in p for p in create_vault.plan(self.vault, "HCR").problems))
        self.assertTrue(create_vault.plan(self.vault, "HCR", push=False).ok)

    def test_git_without_your_name(self):
        git(self.vault, "config", "--unset", "user.email")
        self.assertTrue(any("email" in p for p in create_vault.plan(self.vault, "HCR").problems))

    def test_existing_vault_folders_block_it(self):
        (self.vault / "cad").mkdir()
        self.assertTrue(any("cad" in p for p in create_vault.plan(self.vault, "HCR").problems))

    def test_create_refuses_when_there_are_problems_and_touches_nothing(self):
        with self.assertRaises(create_vault.InitError):
            create_vault.create(self.vault, "H")
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".git"])


class NumberingWarnings(unittest.TestCase):
    def test_nothing_to_say_about_the_defaults(self):
        self.assertEqual(create_vault.numbering_warnings(1, 5, 3), [])

    def test_one_digit_wording(self):
        self.assertIn("1 digit in the part number", create_vault.numbering_warnings(1, 1, 3)[0])

    def test_the_settings_can_be_checked_before_there_is_a_folder(self):
        checked = create_vault.check_settings("hcr", 1, 3, 3)
        self.assertEqual((checked.ok, checked.org), (True, "HCR"))
        self.assertTrue(any("only 999" in w for w in checked.warnings))
        self.assertFalse(create_vault.check_settings("H").ok)
        self.assertTrue(any("doesn't fit" in p for p in create_vault.check_settings("HCR", 100000, 5, 3).problems))


class CommandLine(EmptyRepo):
    @SKIP_ON_WINDOWS
    def test_creates_a_vault(self):
        code = cli_init_vault.main([str(self.vault), "--org", "HCR", "--start", "10001", "--no-team"])
        self.assertEqual(code, 0)
        self.assertEqual(config.get_start_number(self.vault), 10001)

    @SKIP_ON_WINDOWS
    def test_reports_problems_and_changes_nothing(self):
        self.assertEqual(cli_init_vault.main([str(self.vault), "--org", "X"]), 1)
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".git"])

    @SKIP_ON_WINDOWS
    def test_warnings_need_a_yes(self):
        import builtins
        real = builtins.input
        builtins.input = lambda prompt="": "n"
        self.addCleanup(setattr, builtins, "input", real)
        self.assertEqual(cli_init_vault.main([str(self.vault), "--org", "HCR", "--base-digits", "3", "--no-team"]), 1)
        self.assertEqual(sorted(p.name for p in self.vault.iterdir()), [".git"])
        self.assertEqual(cli_init_vault.main([str(self.vault), "--org", "HCR", "--base-digits", "3", "--no-team", "--yes"]), 0)


if __name__ == "__main__":
    unittest.main()
