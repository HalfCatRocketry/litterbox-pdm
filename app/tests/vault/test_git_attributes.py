"""Tests for vault/git_attributes.py (Litterbox's block of rules in .gitattributes, kept up to date) and for the
check in team/guarded_push.py that the vault doesn't need a newer Litterbox before anything is uploaded."""

import unittest

import yaml

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.gui.logic import file_rules_text
from litterbox.team import guarded_push
from litterbox.vault import config_write
from litterbox.vault import git_attributes
from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git

LFS = git_attributes.LFS
OLD_RULES = [f"*.SLDPRT {LFS} lockable", f"*.SLDASM {LFS} lockable", f"*.SLDDRW {LFS} lockable",
             "PN-logs/*.yaml lockable", f"cancelled-revs/** {LFS}"]
OLD_CANCELLED = "cancelled-revs/CANCELLED_HCR-00001-001_B.SLDPRT"             # where 0.6.2 and older kept it
NEW_CANCELLED = "cad/cancelled-revs/CANCELLED_HCR-00001-001_B.SLDPRT"
OLD_FILE = "\n".join(["*.txt text", "", git_attributes.LEGACY_HEADERS[0], *OLD_RULES, "", "# ours", "*.csv text"]) + "\n"


class TheBlock(unittest.TestCase):
    def test_versions(self):
        self.assertIsNone(git_attributes.vault_version(""))
        self.assertIsNone(git_attributes.vault_version("*.txt text\n"))
        self.assertEqual(git_attributes.vault_version(OLD_FILE), 0)
        new_style = "\n".join([git_attributes.LEGACY_HEADERS[1], *git_attributes.RULES]) + "\n"
        self.assertEqual(git_attributes.vault_version(new_style), 0)
        self.assertEqual(git_attributes.vault_version(git_attributes.updated_text("")), git_attributes.VERSION)

    def test_an_empty_file_gets_the_block(self):
        text = git_attributes.updated_text("")
        lines = text.splitlines()
        self.assertEqual(lines[0], git_attributes.BEGIN.format(version=git_attributes.VERSION))
        self.assertEqual(lines[-1], git_attributes.END)
        self.assertEqual(lines[1:-1], git_attributes.RULES)
        self.assertEqual(git_attributes.updated_text(text), text)              # already up to date: unchanged

    def test_old_rules_are_wrapped_and_the_teams_lines_kept(self):
        text = git_attributes.updated_text(OLD_FILE)
        lines = text.splitlines()
        self.assertEqual(lines[:2], ["*.txt text", ""])
        self.assertEqual(lines[-3:], ["", "# ours", "*.csv text"])
        self.assertNotIn(git_attributes.LEGACY_HEADERS[0], lines)
        self.assertNotIn(f"*.SLDPRT {LFS} lockable", lines)               # widened to any capitals
        added = git_attributes.added_rules(OLD_FILE, text)
        self.assertIn(f"{git_attributes.any_case('step')} {LFS} lockable", added)
        self.assertNotIn("PN-logs/*.yaml lockable", added)                  # it was there already

    def test_0_4_0_rules_are_only_marked(self):
        old = "\n".join([git_attributes.LEGACY_HEADERS[1], *git_attributes.RULES]) + "\n"
        text = git_attributes.updated_text(old)
        self.assertEqual(git_attributes.added_rules(old, text), [])
        self.assertEqual(git_attributes.vault_version(text), git_attributes.VERSION)

    def test_an_older_marked_block_is_replaced_in_place(self):
        old = "\n".join(["*.txt text", git_attributes.BEGIN.format(version=0), "*.x lockable", git_attributes.END,
                         "*.csv text"]) + "\n"
        lines = git_attributes.updated_text(old).splitlines()
        self.assertEqual(lines[0], "*.txt text")
        self.assertEqual(lines[-1], "*.csv text")
        self.assertNotIn("*.x lockable", lines)

    def test_a_block_without_its_end_marker_is_refused(self):
        broken = git_attributes.BEGIN.format(version=1) + "\n*.x lockable\n"
        with self.assertRaisesRegex(LitterboxError, "end"):
            git_attributes.updated_text(broken)

    def test_the_question(self):
        text = file_rules_text.question(0, 1, ["  *.step rule"], raises_minimum=True, minimum="0.4.2")
        self.assertIn("0.4.1 or older", text)
        self.assertIn("*.step rule", text)
        self.assertIn("Litterbox 0.4.2 or newer", text)
        self.assertIn("only marked", file_rules_text.question(0, 1, []))
        self.assertIn("none of Litterbox's file rules", file_rules_text.question(None, 1, ["x"]))
        moving = file_rules_text.question(4, 4, [], raises_minimum=True, minimum="0.6.3", moving=2)
        self.assertIn("up to date, but it still has cancelled revisions", moving)
        self.assertIn("The 2 files in the old cancelled-revs folder move there", moving)
        self.assertNotIn("only marked", moving)


@SKIP_ON_WINDOWS
class UpdatingAVault(TwoUserVault, unittest.TestCase):
    LFS = True

    def setUp(self):
        super().setUp()
        with self.user("Alex"):
            config_write.save(self.a, org="HCR", start_number=1, base_digits=5, variant_digits=3)
            (self.a / ".gitattributes").write_text(OLD_FILE, encoding="utf-8")
            (self.a / "cad" / "HCR-00001-001_A.STEP").write_bytes(b"solid step data")    # stored as plain git so far
            (self.a / "cancelled-revs").mkdir()
            (self.a / OLD_CANCELLED).write_bytes(b"a cancelled Rev B")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "A vault from Litterbox 0.3")
            git(self.a, "push")

    def test_needs_update_and_update_converts_files_and_raises_the_minimum(self):
        self.assertEqual(git_attributes.needs_update(self.a), (0, True))
        with self.user("Alex"):
            added = git_attributes.update(self.a)
        self.assertIn(f"{git_attributes.any_case('step')} {LFS} lockable", added)
        self.assertEqual(git_attributes.needs_update(self.a), (git_attributes.VERSION, False))
        stored = git(self.a, "cat-file", "-p", "HEAD:cad/HCR-00001-001_A.STEP")
        self.assertTrue(stored.startswith("version https://git-lfs"), stored)     # now a Git LFS file
        settings = yaml.safe_load((self.a / layout.CONFIG_DIR / layout.CONFIG_FILE).read_text())
        self.assertEqual(settings["min_litterbox_version"], git_attributes.MIN_LITTERBOX)
        self.assertEqual(git(self.a, "status", "--porcelain").strip(), "")
        self.assertEqual(git(self.a, "rev-parse", "HEAD").strip(), git(self.remote, "rev-parse", "main").strip())
        self.assertEqual(git(self.a, "ls-files", "cancelled-revs", "cad/cancelled-revs").splitlines(), [NEW_CANCELLED])
        self.assertEqual((self.a / NEW_CANCELLED).read_bytes(), b"a cancelled Rev B")
        self.assertFalse((self.a / "cancelled-revs").exists())
        self.assertIn("1 cancelled files moved to cad/cancelled-revs", git(self.a, "log", "-1", "--format=%s"))
        with self.user("Alex"):
            self.assertEqual(git_attributes.update(self.a), [])                   # nothing more to do

    def test_cancelled_revisions_left_in_the_old_place_are_still_moved(self):
        with self.user("Alex"):
            git_attributes.update(self.a)
        (self.a / "cancelled-revs").mkdir()                     # an older Litterbox cancelled one meanwhile
        (self.a / OLD_CANCELLED.replace("_B", "_C")).write_bytes(b"a cancelled Rev C")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Cancelled by Litterbox 0.6.2")
        self.assertEqual(git_attributes.needs_update(self.a), (git_attributes.VERSION, True))
        with self.user("Alex"):
            self.assertEqual(git_attributes.update(self.a), [])                   # no rules, but moved
        self.assertIn(NEW_CANCELLED.replace("_B", "_C"), git(self.a, "ls-files", "cad/cancelled-revs").splitlines())
        self.assertEqual(git_attributes.needs_update(self.a), (git_attributes.VERSION, False))

    def test_a_failed_upload_puts_everything_back(self):
        before = (self.a / ".gitattributes").read_bytes()
        head = git(self.a, "rev-parse", "HEAD").strip()
        real = guarded_push.push
        guarded_push.push = lambda repo, attempts=3: (_ for _ in ()).throw(LitterboxError("offline"))
        self.addCleanup(setattr, guarded_push, "push", real)
        with self.user("Alex"), self.assertRaises(LitterboxError):
            git_attributes.update(self.a)
        self.assertEqual((self.a / ".gitattributes").read_bytes(), before)
        self.assertEqual(git(self.a, "rev-parse", "HEAD").strip(), head)
        self.assertEqual(git(self.a, "status", "--porcelain").strip(), "")
        self.assertEqual((self.a / OLD_CANCELLED).read_bytes(), b"a cancelled Rev B")         # moved back
        self.assertFalse((self.a / NEW_CANCELLED).exists())

    def test_a_repository_litterbox_did_not_set_up_is_left_alone(self):
        self.assertFalse((self.b / layout.CONFIG_DIR / layout.CONFIG_FILE).exists())     # Bea hasn't synced
        self.assertEqual(git_attributes.needs_update(self.b), (None, False))


@SKIP_ON_WINDOWS
class UploadsCheckTheVaultFirst(TwoUserVault, unittest.TestCase):
    def test_nothing_is_uploaded_once_the_vault_needs_a_newer_litterbox(self):
        with self.user("Alex"):
            config_write.save(self.a, org="HCR", start_number=1, base_digits=5, variant_digits=3)
            config_write.stamp(self.a, min_version="9.9.9")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Needs a much newer Litterbox")
            git(self.a, "push")
        (self.b / "note.txt").write_text("hello")
        git(self.b, "add", "note.txt")
        git(self.b, "commit", "-m", "Bea's change")
        remote_before = git(self.remote, "rev-parse", "main").strip()
        with self.user("Bea"), self.assertRaisesRegex(LitterboxError, "Nothing was uploaded.*9.9.9"):
            guarded_push.push(self.b)
        self.assertEqual(git(self.remote, "rev-parse", "main").strip(), remote_before)


if __name__ == "__main__":
    unittest.main()
