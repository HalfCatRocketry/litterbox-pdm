"""
Shared setup for tests that need two users and a shared remote vault.

TwoUserVault builds, in a temporary folder:
    remote.git   a bare repo standing in for GitHub / Azure
    a            Alex's copy of the vault
    b            Bea's copy of the vault
and puts tests/support/fake_git_lfs.py in place of Git LFS (see that file for why).

Set LFS = True on a test class to store the CAD files through (fake) Git LFS from the first commit, as a real vault
does; set ON_DEMAND = True as well to make Bea's copy download on demand (cloned without the CAD files, like
Add org... makes it).

The vault starts with one part, HCR-00001-001, with a part file, a drawing,
and a record. Use `with self.user("Alex"):` to act as one user or the other.

These tests need a Unix-like system (Linux, macOS or WSL), so the test classes
that use this are marked @SKIP_ON_WINDOWS.
"""

import atexit
import contextlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import temp_folders
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.git import lfs_locks
from litterbox.parts import part_status
from litterbox.git import read_only

SHIM = Path(__file__).with_name("fake_git_lfs.py")
PART = PN("HCR", 1, 1)
PRT = "cad/HCR-00001-001_A.SLDPRT"
DRW = "cad/HCR-00001-001_A.SLDDRW"
REC = "PN-logs/HCR-00001-001.yaml"

# The git tests take a long time, so on Windows they run only when asked: set LITTERBOX_GIT_TESTS=1 (Git for Windows
# runs the fake git-lfs through its own sh, with the python3 wrapper setUp puts beside it).
SKIP_ON_WINDOWS = unittest.skipIf(os.name == "nt" and os.environ.get("LITTERBOX_GIT_TESTS") != "1",
                                  "a git test: set LITTERBOX_GIT_TESTS=1 to run it on Windows (slow)")


def install_fake_lfs(bin_dir):
    """Put the fake git-lfs in `bin_dir` (which goes first on PATH). On Windows, Git runs it through its own sh, and
    its #!/usr/bin/env python3 line needs a python3 there: a small one beside it runs this Python."""
    shim = Path(bin_dir) / "git-lfs"
    shutil.copy(SHIM, shim)
    shim.chmod(0o755)
    if os.name == "nt":
        python3 = Path(bin_dir) / "python3"
        python3.write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', newline="\n")


def git(folder, *args):
    result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def is_writable(path):
    return bool(stat.S_IMODE(os.stat(path).st_mode) & stat.S_IWUSR)


_TEMPLATES = {}         # (LFS, ON_DEMAND): a folder holding the vault as setUp leaves it, built once per process


class TwoUserVault:
    """Mix this into a unittest.TestCase."""

    LFS = False                 # store CAD files through the fake Git LFS
    ON_DEMAND = False           # Bea's copy downloads on demand (needs LFS)

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, root)
        self.root = root
        saved_env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved_env)))

        # The vault is built once per process (and kind of vault), then copied: building it runs about fifteen git
        # commands, a third of a short git test's time. The copies' remotes are pointed at their own remote.git.
        key = (self.LFS, self.ON_DEMAND)
        if key not in _TEMPLATES:
            template = Path(tempfile.mkdtemp(prefix="litterbox-test-vault-"))
            atexit.register(temp_folders.remove, template)
            self._use(template, saved_env)
            self._build(template)
            _TEMPLATES[key] = template
        self._use(root, saved_env)
        shutil.copytree(_TEMPLATES[key], root, dirs_exist_ok=True)
        self.remote, self.a, self.b = root / "remote.git", root / "a", root / "b"
        for clone in (self.a, self.b):
            git(clone, "remote", "set-url", "origin", str(self.remote))

    def _use(self, root, saved_env):
        """Point git, the fake git-lfs and its lock store at this folder: the fake git-lfs first on PATH, this
        computer's own Git settings (e.g. commit signing) ignored."""
        os.environ["PATH"] = f"{root / 'bin'}{os.pathsep}{saved_env['PATH']}"
        os.environ["LFS_STORE"] = str(root / "locks.json")
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
        os.environ["GIT_CONFIG_GLOBAL"] = str(root / "empty-gitconfig")
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        if self.LFS or self.ON_DEMAND:
            os.environ["LFS_OBJECTS"] = str(root / "lfs-objects")      # the LFS "server"

    def _build(self, root):
        """The vault as every test starts with it, in `root` (the environment already points at it)."""
        bin_dir = root / "bin"
        bin_dir.mkdir()
        install_fake_lfs(bin_dir)
        empty_config = root / "empty-gitconfig"
        empty_config.write_text("")
        if self.LFS or self.ON_DEMAND:
            for key, value in (("filter.lfs.clean", "git-lfs clean -- %f"),
                               ("filter.lfs.smudge", "git-lfs smudge -- %f"), ("filter.lfs.required", "true")):
                subprocess.run(["git", "config", "--file", str(empty_config), key, value], check=True)

        git(root, "init", "--bare", "-b", "main", "remote.git")
        remote = str(root / "remote.git")

        # Alex starts the vault: one part with a part file, a drawing, and a record.
        a = root / "a"
        git(root, "clone", remote, "a")
        git(a, "symbolic-ref", "HEAD", "refs/heads/main")
        self.config(a, "Alex")
        (a / "cad").mkdir()
        if self.LFS or self.ON_DEMAND:
            (a / ".gitattributes").write_text("".join(f"*.{ext} filter=lfs -text\n"
                                                      for ext in ("SLDPRT", "SLDASM", "SLDDRW")))
        (a / PRT).write_bytes(b"version 1")
        (a / DRW).write_bytes(b"drawing 1")
        record_store.create_record(a, PART, "Front upright", "Alex")
        git(a, "add", ".")
        git(a, "commit", "-m", "Start vault")
        git(a, "push", "-u", "origin", "main")

        b = root / "b"
        if self.ON_DEMAND:                                  # like Add org...: no CAD files, then download on demand
            os.environ["GIT_LFS_SKIP_SMUDGE"] = "1"
            try:
                git(root, "clone", remote, "b")
            finally:
                del os.environ["GIT_LFS_SKIP_SMUDGE"]
            git(b, "lfs", "install", "--local", "--skip-smudge")
        else:
            git(root, "clone", remote, "b")
        self.config(b, "Bea")

        with self.user("Alex"):
            read_only.enforce_read_only(a)
        with self.user("Bea"):
            read_only.enforce_read_only(b)

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
        record_store.create_record(self.a, pn, description, "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", f"Create {pn}")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        return pn
