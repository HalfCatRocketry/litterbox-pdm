"""
downloads.py - downloading what a part needs, when it needs it (download on demand).

A vault can download on demand (your setting `download` in settings.yaml, see user/settings.py): CAD files then stay
small pointer files until they are used. Check Out downloads the part's files; Open downloads the revision you open
and, for an assembly, every part revision it uses (from the records, so nothing has to be opened to find out);
Get Latest keeps what you already have up to date (git/remote.pull). Download All gets everything.

Release, Make COTS, Unrelease and Void only change the record, so they never download anything.
"""

from pathlib import Path

from litterbox.core import toolbox_rules
from litterbox.git import lfs_download
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_other_files
from litterbox.records import record_store
from litterbox.references import reference_model


def files_to_open(repo, pn, revision):
    """The files needed to open one revision of a part: its own, and for an assembly every part revision it uses
    (and what those use, and so on), and the other files in the vault it uses (the team's Toolbox parts,
    records/record_other_files.py). Parts or revisions the vault doesn't have are skipped."""
    index = record_files.cad_index(repo)
    needed, seen, todo = [], set(), [(pn, revision)]
    while todo:
        part, rev = todo.pop()
        if (part, rev) in seen:
            continue
        seen.add((part, rev))
        needed += index.get(part, {}).get(rev, [])
        try:
            record = record_store.load(repo, part)
        except record_model.RegistryError:
            continue
        needed += [entry["file"] for entry in record_other_files.entries(record, rev)
                   if toolbox_rules.in_vault(entry["file"]) and (Path(repo) / entry["file"]).is_file()]
        for stem in record.references.get(rev, []):
            used = reference_model.split_stem(stem)
            if used is not None:
                todo.append(used)
    return sorted(set(needed))


def download_for_open(repo, pn, revision):
    """Download whatever opening this revision needs. Returns the files downloaded (empty if all were there)."""
    return lfs_download.download(repo, files_to_open(repo, pn, revision), f"files for {pn} Rev {revision}")


def download_files(repo, rels, label="files"):
    """Download these files if they are not on disk yet. Returns the files downloaded."""
    return lfs_download.download(repo, rels, label)


def download_all(repo):
    """Download every CAD file of the vault (Download All). From then on, Get Latest keeps them all up to date."""
    lfs_download.download_everything(repo)


def apply_mode(repo, on_demand):
    """Make this vault download on demand (True) or everything (False), if it doesn't already. Returns True if it
    changed. Turning on-demand off downloads everything at once."""
    if lfs_download.is_on_demand(repo) == bool(on_demand):
        return False
    lfs_download.set_on_demand(repo, on_demand)
    if not on_demand:
        lfs_download.download_everything(repo)
    return True
