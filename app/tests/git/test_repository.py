"""git/repository.get_modified: every kind of change, with names git would otherwise quote (spaces, letters like é)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from litterbox.git import repository
from tests.support import temp_folders


def git(folder, *args):
    subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)


class SmallRepo:
    """Mix into a TestCase: a git repository with a few committed files in cad/, some with names git would quote."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.repo)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        empty = self.repo.parent / f"{self.repo.name}-gitconfig"
        empty.write_text("")
        self.addCleanup(empty.unlink)
        os.environ["GIT_CONFIG_GLOBAL"] = str(empty)          # ignore this computer's own git settings
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Alex")
        git(self.repo, "config", "user.email", "alex@example.com")
        (self.repo / "cad").mkdir()
        for name in ("Plain.txt", "Café part.txt", "Gone.txt", "Old name.txt", "Staged.txt"):
            (self.repo / "cad" / name).write_text("one\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "start")


class GetModified(SmallRepo, unittest.TestCase):
    def test_a_clean_copy_has_nothing(self):
        self.assertEqual(repository.get_modified(self.repo), set())

    def test_every_kind_of_change(self):
        (self.repo / "cad" / "Plain.txt").write_text("two\n", encoding="utf-8")
        (self.repo / "cad" / "Café part.txt").write_text("two\n", encoding="utf-8")
        (self.repo / "cad" / "Gone.txt").unlink()
        git(self.repo, "mv", "cad/Old name.txt", "cad/New name.txt")
        (self.repo / "cad" / "Staged.txt").write_text("two\n", encoding="utf-8")
        git(self.repo, "add", "cad/Staged.txt")
        (self.repo / "cad" / "new folder").mkdir()
        (self.repo / "cad" / "new folder" / "Brand néw.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(repository.get_modified(self.repo), {
            "cad/plain.txt", "cad/café part.txt", "cad/gone.txt", "cad/old name.txt", "cad/new name.txt",
            "cad/staged.txt", "cad/new folder/brand néw.txt"})


class InHeadMany(SmallRepo, unittest.TestCase):
    def test_only_the_files_in_the_latest_commit(self):
        (self.repo / "cad" / "Not yet.txt").write_text("new\n", encoding="utf-8")
        git(self.repo, "add", "cad/Not yet.txt")
        asked = ["cad/Plain.txt", "cad/Café part.txt", "cad/Not yet.txt", "cad/missing.txt"]
        self.assertEqual(repository.in_head_many(self.repo, asked), {"cad/Plain.txt", "cad/Café part.txt"})
        self.assertEqual({rel for rel in asked if repository.in_head(self.repo, rel)},
                         repository.in_head_many(self.repo, asked))

    def test_nothing_asked(self):
        self.assertEqual(repository.in_head_many(self.repo, []), set())

    def test_paths_changed_in_unpushed_and_incoming_commits(self):
        remote = self.repo.parent / f"{self.repo.name}-remote.git"
        self.addCleanup(temp_folders.remove, remote)
        git(self.repo.parent, "init", "-q", "--bare", "-b", "main", str(remote))
        self.assertEqual(repository.paths_changed_in(self.repo, repository.UNPUSHED), set())     # no upstream yet
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.assertEqual(repository.paths_changed_in(self.repo, repository.UNPUSHED), set())

        other = self.repo.parent / f"{self.repo.name}-other"
        self.addCleanup(temp_folders.remove, other)
        git(self.repo.parent, "clone", "-q", str(remote), str(other))
        git(other, "config", "user.name", "Bea")
        git(other, "config", "user.email", "bea@example.com")
        (other / "cad" / "Gone.txt").write_text("theirs\n", encoding="utf-8")
        git(other, "commit", "-q", "-am", "theirs")
        git(other, "push", "-q")

        (self.repo / "cad" / "Café part.txt").write_text("mine\n", encoding="utf-8")
        git(self.repo, "commit", "-q", "-am", "one")
        git(self.repo, "mv", "cad/Old name.txt", "cad/New name.txt")
        git(self.repo, "commit", "-q", "-m", "two")
        git(self.repo, "fetch", "-q")
        self.assertEqual(repository.paths_changed_in(self.repo, repository.UNPUSHED),
                         {"cad/Café part.txt", "cad/Old name.txt", "cad/New name.txt"})
        self.assertEqual(repository.paths_changed_in(self.repo, repository.INCOMING), {"cad/Gone.txt"})

    def test_many_files_are_asked_in_pieces(self):
        names = [f"cad/part {n}.txt" for n in range(250)]
        for name in names:
            (self.repo / name).write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "cad")
        git(self.repo, "commit", "-q", "-m", "many")
        self.assertEqual(repository.in_head_many(self.repo, names + ["cad/missing.txt"]), set(names))


if __name__ == "__main__":
    unittest.main()
