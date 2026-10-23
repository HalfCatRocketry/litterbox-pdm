"""
sparse.py - leaving some of the vault's files out of this copy (a hidden project's parts, vault/project_visibility.py).

Git's sparse checkout keeps the files matching `excluded` out of the working folder (git still follows them, so
pulls and pushes work as usual), and Git LFS's fetchexclude keeps their large files from ever being downloaded.
Patterns are git's: '/PN-logs/HCR-12*' (from the top of the vault). The smaller text of their records still comes
down inside git's own compressed history, as everything in a vault's history does.

    sparse.set_excluded(repo, ["/PN-logs/HCR-12*", "/cad/HCR-12*"])      # leave them out
    sparse.set_excluded(repo, [])                                        # everything again
"""

import os
import stat
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import runner


def _file(repo):
    """The sparse-checkout file, wherever this copy keeps git's own files."""
    path = Path(runner.run(["git", "rev-parse", "--git-path", "info/sparse-checkout"], repo, quiet=True).strip())
    return path if path.is_absolute() else Path(repo) / path


def _is_on(repo):
    try:
        return runner.run(["git", "config", "--get", "core.sparseCheckout"], repo, quiet=True).strip() == "true"
    except LitterboxError:
        return False


def excluded(repo):
    """The patterns this copy leaves out now ([] when it has everything)."""
    if not _is_on(repo):
        return []
    try:
        lines = _file(repo).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line[1:] for line in lines if line.startswith("!")]


def lfs_pattern(pattern):
    """'/cad/HCR-12*' -> 'cad/HCR-12*': Git LFS's patterns don't start with a slash."""
    return pattern.lstrip("/")


def set_excluded(repo, patterns):
    """Leave the files matching `patterns` out of this copy, and bring back any no longer left out. Does nothing
    when the copy already matches. Raises LitterboxError if git can't (a changed file in the way is left alone)."""
    patterns = sorted(dict.fromkeys(patterns))
    if patterns == sorted(excluded(repo)):
        return False
    lfs = [lfs_pattern(p) for p in patterns if not p.startswith(f"/{layout.LOG_DIR_NAME}/")]
    if lfs:
        runner.run(["git", "config", "lfs.fetchexclude", ",".join(lfs)], repo, quiet=True)
    else:
        _unset(repo, "lfs.fetchexclude")
    if not patterns:
        runner.run(["git", "sparse-checkout", "disable"], repo, quiet=True)
        return True
    for found in _matching(repo, patterns):     # Windows won't let git delete a read-only file
        os.chmod(found, stat.S_IREAD | stat.S_IWRITE)
    try:                                        # making files read-only changed their times: git would take
        runner.run(["git", "update-index", "-q", "--refresh"], repo, quiet=True)     # them for changed ones
    except LitterboxError:
        pass                                    # some really are changed: git leaves those, and says so below
    runner.run(["git", "sparse-checkout", "set", "--no-cone", "/*"] + [f"!{p}" for p in patterns], repo, quiet=True)
    left = _matching(repo, patterns)
    if left:
        diagnostics.LOG(f"WARNING: git kept {len(left)} file(s) a hidden project should leave out, because they are "
                        f"changed in this copy: " + ", ".join(str(p.relative_to(repo)) for p in left[:5]))
    return True


def _matching(repo, patterns):
    """The files in the working folder that these patterns match."""
    return [found for pattern in patterns for found in Path(repo).glob(pattern.lstrip("/")) if found.is_file()]


def _unset(repo, key):
    try:
        runner.run(["git", "config", "--unset", key], repo, quiet=True)
    except LitterboxError:
        pass                                    # it wasn't set
