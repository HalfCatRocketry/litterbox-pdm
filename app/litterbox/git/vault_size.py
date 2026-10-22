"""
vault_size.py - how much the vault takes up (Vault > Vault Size...): its history (every commit, as git stores it)
and its Git LFS files (every version any commit points to, each counted once), as your copy of the vault knows
them after a fetch. It also says how much of the LFS part is downloaded on this computer.

The host stores about the same. Two things a copy can't see: LFS files no commit points to any more (after the
history was rewritten), which the host may still keep and count, and branches nobody fetched. The host's own
storage page is the last word.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from litterbox.errors import LitterboxError
from litterbox.git import runner


@dataclass
class VaultSize:
    commits: int = 0
    history_bytes: int = 0          # the git objects: every commit, record and small file, packed or loose
    lfs_files: int = 0              # LFS files, every version, each once
    lfs_bytes: int = 0
    downloaded_files: int = 0       # of those, the ones on this computer
    downloaded_bytes: int = 0
    fetched: bool = True            # False: the host couldn't be reached, so this is the copy as it was


def history_bytes(count_objects):
    """Bytes of git objects from `git count-objects -v` (it says KiB): loose ('size') and packed ('size-pack')."""
    found = {}
    for line in count_objects.splitlines():
        key, _sep, value = line.partition(":")
        if value.strip().isdigit():
            found[key.strip()] = int(value.strip())
    return (found.get("size", 0) + found.get("size-pack", 0)) * 1024


def lfs_objects(ls_files_json):
    """{oid: bytes} from `git lfs ls-files --all --json`, each object once however many files and commits use it."""
    try:
        files = json.loads(ls_files_json or "{}").get("files") or []
    except (ValueError, AttributeError):
        raise LitterboxError("Git LFS gave a list Litterbox couldn't read. Git LFS 3.4 or newer is needed.") from None
    return {f["oid"]: int(f.get("size") or 0) for f in files if f.get("oid")}


def is_downloaded(repo, oid):
    """True if this LFS object is in this computer's copy (.git/lfs/objects/ab/cd/abcd...)."""
    return (Path(repo) / ".git" / "lfs" / "objects" / oid[:2] / oid[2:4] / oid).is_file()


def measure(repo):
    """Fetch (if the host answers), then measure. Returns a VaultSize. Raises LitterboxError if git fails."""
    size = VaultSize()
    try:
        runner.run(["git", "fetch", "--quiet", "origin"], repo)
    except LitterboxError:
        size.fetched = False
    size.commits = int(runner.run(["git", "rev-list", "--all", "--count"], repo, quiet=True).strip() or 0)
    size.history_bytes = history_bytes(runner.run(["git", "count-objects", "-v"], repo, quiet=True))
    objects = lfs_objects(runner.run(["git", "lfs", "ls-files", "--all", "--json"], repo, quiet=True))
    size.lfs_files, size.lfs_bytes = len(objects), sum(objects.values())
    here = [oid for oid in objects if is_downloaded(repo, oid)]
    size.downloaded_files, size.downloaded_bytes = len(here), sum(objects[oid] for oid in here)
    return size
