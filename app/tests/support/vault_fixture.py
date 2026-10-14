"""
Shared setup for tests that need two users and a shared remote vault.

TwoUserVault builds, in a temporary folder:
    remote.git   a bare repo standing in for GitHub / Azure
    a            Alex's copy of the vault
    b            Bea's copy of the vault
and puts tests/fake_git_lfs.py in place of Git LFS (see that file for why).

The vault starts with one part, HCR-00001-001, with a part file, a drawing,
and a record. Use `with self.user("Alex"):` to act as one user or the other.

These tests need a Unix-like system (Linux, macOS or WSL), so the test classes
that use this are marked @SKIP_ON_WINDOWS.
"""

import contextlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from litterbox.records import registry
from litterbox.core.pn import PN
from litterbox.git import lfs_locks
from litterbox.parts import part_status
from litterbox.git import read_only

SHIM = Path(__file__).with_name("fake_git_lfs.py")
PART = PN("HCR", 1, 1)
PRT = "cad/HCR-00001-001_A.SLDPRT"
DRW = "cad/HCR-00001-001_A.SLDDRW"
REC = "PN-logs/HCR-00001-001.yaml"

SKIP_ON_WINDOWS = unittest.skipIf(os.name == "nt", "uses a fake git-lfs script; run on Linux, macOS or WSL")


def git(folder, *args):
    result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def is_writable(path):
    return bool(stat.S_IMODE(os.stat(path).st_mode) & stat.S_IWUSR)


class TwoUserVault:
    """Mix this into a unittest.TestCase."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.root = root

        # Put the fake git-lfs first on PATH so `git lfs ...` finds it.
        bin_dir = root / "bin"
        bin_dir.mkdir()
        shim = bin_dir / "git-lfs"
        shutil.copy(SHIM, shim)
        shim.chmod(0o755)
        saved_env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved_env)))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
        os.environ["LFS_STORE"] = str(root / "locks.json")
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
        empty_config = root / "empty-gitconfig"          # ignore this computer's own Git settings (e.g. commit signing)
        empty_config.write_text("")
        os.environ["GIT_CONFIG_GLOBAL"] = str(empty_config)
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

        git(root, "init", "--bare", "-b", "main", "remote.git")
        remote = str(root / "remote.git")
        self.remote = root / "remote.git"

        # Alex starts the vault: one part with a part file, a drawing, and a record.
        self.a = root / "a"
        git(root, "clone", remote, "a")
        git(self.a, "symbolic-ref", "HEAD", "refs/heads/main")
        self.config(self.a, "Alex")
        (self.a / "cad").mkdir()
        (self.a / PRT).write_bytes(b"version 1")
        (self.a / DRW).write_bytes(b"drawing 1")
        registry.create_record(self.a, PART, "Front upright", "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Start vault")
        git(self.a, "push", "-u", "origin", "main")

        self.b = root / "b"
        git(root, "clone", remote, "b")
        self.config(self.b, "Bea")

        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        with self.user("Bea"):
            read_only.enforce_read_only(self.b)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def config(folder, name):
        git(folder, "config", "user.name", name)
        git(folder, "config", "user.email", f"{name.lower()}@example.com")

    @contextlib.contextmanager
    def user(self, name):
        previous = os.environ.get("LFS_USER")
        os.environ["LFS_USER"] = name
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("LFS_USER", None)
            else:
                os.environ["LFS_USER"] = previous

    def status_of(self, repo, pn=PART):
        return next(row for row in part_status.get_status(repo) if row.pn == pn)

    def remote_log(self):
        return git(self.remote, "log", "--format=%s", "main").splitlines()

    def locks(self, repo):
        return lfs_locks.get_locks(repo, strict=True)

    def add_created_part(self, base, description="Created"):
        """Alex creates a new PN (record only, no CAD files yet) and pushes it."""
        pn = PN("HCR", base, 1)
        registry.create_record(self.a, pn, description, "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", f"Create {pn}")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        return pn
