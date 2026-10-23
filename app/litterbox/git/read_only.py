"""
read_only.py - Git LFS pointer files, keeping other people's files read-only, and deleting files that may be
read-only.

Read-only is the safety net: only the person who holds a part's lock gets writable files. enforce_read_only runs
after pulls, check-ins and undo, and only touches files of parts that have records.
"""

import os
import stat
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.records import record_files
from litterbox.records import record_store


POINTER_MAX_SIZE = 300          # bytes: an LFS pointer file is never bigger


def is_pointer(path):
    """True if the file is a tiny LFS pointer, meaning the real file wasn't downloaded."""
    try:
        if path.stat().st_size > POINTER_MAX_SIZE:
            return False
        with open(path, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def _set_read_only(path):
    """Make a file read-only, unless it already is: changing nothing keeps its times as they are, so git doesn't
    have to look at the file again (on Linux every chmod changes a file's ctime)."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if stat.S_ISREG(mode) and mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        os.chmod(path, stat.S_IREAD)


def delete_file(path):
    """Delete a file, even a read-only one (Windows refuses to delete those). Nothing happens if it isn't there.
    Raises OSError if it can't be deleted (open in SolidWorks, say)."""
    path = Path(path)
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except FileNotFoundError:
        return
    path.unlink()


def delete_files(repo, rels):
    """delete_file() for each of these vault files. Returns a line for each one that couldn't be ("cad/x: why")."""
    problems = []
    for rel in rels:
        try:
            delete_file(Path(repo) / rel)
        except OSError as e:
            problems.append(f"{rel}: {e}")
    return problems


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
    index = record_files.cad_index(repo)
    for pn in record_store.list_pns(repo) + record_store.list_docs(repo):
        every_file = [f for files in index.get(pn, {}).values() for f in files]
        for rel in every_file + [record_store.record_relpath(pn)]:
            if not lfs_locks.is_mine(locks, rel):
                _set_read_only(Path(repo) / rel)
    eco_folder = Path(repo) / layout.ECO_DIR_NAME          # change orders: only Litterbox writes them, never by hand
    if eco_folder.is_dir():
        for file in eco_folder.glob("*.yaml"):
            _set_read_only(file)
