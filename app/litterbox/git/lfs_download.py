"""
lfs_download.py - CAD files that are not downloaded yet, and downloading them.

A vault can download on demand (set_on_demand): git then leaves every CAD file as a small Git LFS pointer file (a
"stub", about 130 bytes) until it is needed, and Litterbox downloads exactly the files it needs with
`git lfs pull --include=...`. A pointer holds the real file's SHA-256, so its fingerprint is known without
downloading it (pointer_oid).

Downloading replaces each pointer with the real file and gives it back its read-only / writable state, so the
read-only safety net is the same before and after.
"""

import os
import re
import stat
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.git import runner

CHUNK = 50                      # paths per `git lfs pull`, so the command line stays short
_OID = re.compile(rb"^oid sha256:([0-9a-f]{64})$", re.M)
_SIZE = re.compile(rb"^size (\d+)$", re.M)


def is_stub(repo, rel):
    """True if this file of the vault is a pointer, not the real file."""
    return read_only.is_pointer(Path(repo) / rel)


def stubs(repo, rels):
    """The files among these that are not downloaded (missing files are left out)."""
    return [rel for rel in rels if is_stub(repo, rel)]


def pointer_info(path):
    """(SHA-256 hex, size in bytes) of the real file a pointer stands for, or None if `path` is not a pointer."""
    if not read_only.is_pointer(Path(path)):
        return None
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    oid, size = _OID.search(data), _SIZE.search(data)
    return (oid.group(1).decode("ascii"), int(size.group(1))) if oid and size else None


def pointer_oid(path):
    """The SHA-256 (hex) of the real file a pointer stands for, or None if `path` is not a pointer."""
    info = pointer_info(path)
    return info[0] if info else None


def downloaded_cad_files(repo):
    """Every file in the cad folder that is on disk for real (not a pointer), relative to the vault."""
    try:
        entries = os.scandir(Path(repo) / layout.CAD_DIR_NAME)
    except OSError:                                    # no cad folder
        return []
    with entries:                                      # a big file can't be a pointer: only small ones are opened
        return [f"{layout.CAD_DIR_NAME}/{entry.name}" for entry in entries if entry.is_file()
                and (entry.stat().st_size > read_only.POINTER_MAX_SIZE or not read_only.is_pointer(Path(entry.path)))]


def download(repo, rels, label="files"):
    """Download these files if they are pointers. Returns the ones that were downloaded. Raises LitterboxError if
    any is still a pointer afterwards (offline, or the file is missing on the server)."""
    wanted = stubs(repo, rels)
    if not wanted:
        return []
    diagnostics.LOG(f"Downloading {len(wanted)} {label}...")
    modes = {}
    for rel in wanted:                      # git-lfs may not replace a read-only file on Windows: open it up first
        path = Path(repo) / rel
        modes[rel] = path.stat().st_mode
        os.chmod(path, modes[rel] | stat.S_IWUSR)
    try:
        for start in range(0, len(wanted), CHUNK):
            chunk = wanted[start:start + CHUNK]
            runner.run(["git", "lfs", "pull", f"--include={','.join(chunk)}"], repo)
            # git remembers each file's size; a pointer and the real file differ, so git would call the file
            # modified without looking. Adding them again (same content, so nothing is staged) updates that.
            runner.run(["git", "add", "--", *[rel for rel in chunk if (Path(repo) / rel).exists()]], repo, quiet=True)
    finally:
        for rel, mode in modes.items():     # give each file back its read-only / writable state
            path = Path(repo) / rel
            if path.exists():
                os.chmod(path, stat.S_IMODE(mode))
    left = stubs(repo, wanted)
    if left:
        raise LitterboxError("These files could not be downloaded:\n  " + "\n  ".join(left[:10])
                             + ("\n  ..." if len(left) > 10 else "") + "\n\nAre you online?")
    return wanted


def download_everything(repo):
    """Download every CAD file of the vault (Download All)."""
    runner.run(["git", "lfs", "pull"], repo)


def is_on_demand(repo):
    """True if git leaves CAD files as pointers in this vault (git-lfs's smudge filter is set to skip)."""
    try:
        config = runner.run(["git", "config", "--get-regexp", r"^filter\.lfs\.(smudge|process)$"], repo, quiet=True)
    except LitterboxError:
        return False
    return "--skip" in config


def set_on_demand(repo, on_demand):
    """Make this vault download on demand (True) or download everything as usual (False). Changes only this
    vault's git settings; files already on disk stay as they are."""
    command = ["git", "lfs", "install", "--local"] + (["--skip-smudge"] if on_demand else [])
    runner.run(command, repo, quiet=True)
