"""
read_only.py - Git LFS pointer files, and keeping other people's files
read-only.

Read-only is the safety net: only the person who holds a part's lock gets writable files. enforce_read_only runs
after pulls, check-ins and undo, and only touches files of parts that have records.
"""

import os
import stat
from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.records import registry


def is_pointer(path):
    """True if the file is a tiny LFS pointer, meaning the real file wasn't downloaded."""
    try:
        if path.stat().st_size > 300:
            return False
        with open(path, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def _set_read_only(path):
    if path.is_file():
        os.chmod(path, stat.S_IREAD)


def enforce_read_only(repo):
    """Make every managed file read-only unless you hold its lock.

    This is the safety net that stops SolidWorks from saving over a file you
    haven't checked out. It runs after every pull, check-in, undo and so on.
    If the lock list can't be read, it does nothing: guessing wrong here would
    lock you out of files you are editing.
    """
    try:
        locks = lfs_locks.get_locks(repo, strict=True)
    except LitterboxError:
        diagnostics.LOG("WARNING: skipped the read-only check because locks could not be read.")
        return
    index = registry.cad_index(repo)
    for pn in registry.list_pns(repo):
        every_file = [f for files in index.get(pn, {}).values() for f in files]
        for rel in every_file + [registry.record_relpath(pn)]:
            if not lfs_locks.is_mine(locks, rel):
                _set_read_only(Path(repo) / rel)
