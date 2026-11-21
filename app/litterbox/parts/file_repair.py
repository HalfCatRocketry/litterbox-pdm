"""
file_repair.py - Repair Files (Vault menu): putting back the vault's copy of files that went wrong on this computer.

A CAD file or document you don't have checked out should be exactly the vault's copy: Litterbox keeps it read-only.
If it isn't (a download or a sync cut off part-way, a program killed while writing it, a disk or sync-tool problem),
nothing else in Litterbox puts it right: Download All and Open only fill in files that are still pointers, and Undo
Checkout needs your lock. In the list such a part shows as "Modified but not checked out" or "Released, but its
files were modified".

find() lists them: files in cad/ and documents/ that differ from the last commit (or are missing) and that you don't
hold the lock on. Files you have checked out are never touched; Undo Checkout is for those. repair() puts back the
vault's copy of each (`git restore --source=HEAD`), downloads it again, and makes it read-only again. Changes in
those files are lost, which is why the window lists them and asks first.
"""

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner

FOLDERS = (layout.CAD_DIR_NAME, layout.DOC_DIR_NAME)


@dataclass
class RepairResult:
    repaired: list = field(default_factory=list)          # put back and on disk for real (or a pointer, if it was one)
    failed: dict = field(default_factory=dict)            # {file: why} for those git couldn't put back
    not_downloaded: list = field(default_factory=list)    # put back, but still a pointer: the download failed


def find(repo, locks=None):
    """The vault files on this computer that don't match the vault's copy and that you don't have checked out,
    sorted. Asks the server for the lock list (raises LitterboxError if it can't: guessing could lose your work)."""
    repository.validate_repo(repo)
    out = runner.run(["git", "diff", "--name-only", "-z", "--no-renames", "HEAD", "--", *FOLDERS], repo, quiet=True)
    changed = [rel for rel in out.split("\0") if rel]
    if not changed:
        return []
    if locks is None:
        locks = lfs_locks.get_locks(repo, strict=True)
    return sorted(rel for rel in changed if not lfs_locks.is_mine(locks, rel))


def _writable(repo, rels):
    for rel in rels:                        # git may not replace a read-only file on Windows
        try:
            path = Path(repo) / rel
            os.chmod(path, stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
        except OSError:
            pass                            # missing: git puts it back


def _restore(repo, rels):
    """git restore each file from the last commit. Returns {file: why} for the ones it couldn't."""
    failed = {}
    for start in range(0, len(rels), runner.CHUNK):
        chunk = rels[start:start + runner.CHUNK]
        try:
            runner.run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", *chunk], repo)
        except LitterboxError:              # one file held open stops the lot: try each on its own, to say which
            for rel in chunk:
                try:
                    runner.run(["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", rel], repo,
                               quiet=True)
                except LitterboxError as e:
                    lines = [line.strip() for line in str(e).splitlines() if line.strip()]
                    failed[rel] = lines[-1] if lines else "git couldn't put it back"
    return failed


@diagnostics.timed("repair files")
def repair(repo, rels):
    """Put back the vault's copy of these files (from find()), download them, and make them read-only again. Files
    you have checked out by now are skipped. Returns a RepairResult."""
    repository.validate_repo(repo)
    locks = lfs_locks.get_locks(repo, strict=True)
    rels = [rel for rel in rels if not lfs_locks.is_mine(locks, rel)]
    result = RepairResult()
    if not rels:
        return result
    diagnostics.LOG(f"Repairing {len(rels)} files: putting back the vault's copy")
    _writable(repo, rels)
    result.failed = _restore(repo, rels)
    restored = [rel for rel in rels if rel not in result.failed]
    try:            # download on demand: git put back a pointer, so download the real file
        lfs_download.download(repo, lfs_download.stubs(repo, restored), "repaired files")
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: some repaired files could not be downloaded. {e}")
    result.not_downloaded = lfs_download.stubs(repo, restored)
    result.repaired = [rel for rel in restored if rel not in result.not_downloaded]
    read_only.enforce_read_only(repo, locks)
    return result
