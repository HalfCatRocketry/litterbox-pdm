"""
part_status.py - the status of every part: one row per record in
PN-logs, with its lock, its files and whether they are modified.

Rows come from records, not files: a CAD file with no record has no row.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.core import revision_letters
from litterbox.core.part_number import PN
from litterbox.exporting import step_pdf
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.records import record_exports
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store


@dataclass
class PartStatus:
    pn: PN
    name: str
    record_status: str          # in_work / released / void
    state: str                  # text to show the user
    kind: str                   # ok, mine, theirs, unclaimed, stray, missing, released, void, error
    locked_by: str = ""
    files: list = field(default_factory=list)   # CAD files, relative to the repo
    description: str = ""
    cots: bool = False
    import_path: str = ""
    revision: str = "A"                 # the working (latest) revision; `files` are this revision's files
    released_revision: str = ""         # the latest released revision, if any
    revisions: dict = field(default_factory=dict)   # {revision: [files]} for every revision that has files
    refs_outdated: bool = False         # an assembly whose list of parts used is missing or out of date
    pending: dict = field(default_factory=dict)     # a release request waiting for sign-offs (see workflow.py)
    not_downloaded: bool = False        # the working revision's files are pointers (see git/lfs_download.py)
    project: str = ""                   # the project it belongs to (core/projects.py), "" for none
    bom_outdated: bool = False          # an assembly whose part counts are missing or out of date
    released_revisions: tuple = ()      # every revision that has been released, oldest first
    files_needed: tuple = ()            # the STEP and/or PDF its released revision still needs (record_exports.py)


def released_revisions(record):
    """Every revision of a record that has been released, oldest first."""
    released = {e.get("revision") for e in record.history
                if e.get("event") == record_model.EVENT_RELEASED and e.get("revision")}
    return tuple(sorted(released, key=revision_letters.revision_number))


def get_status(repo):
    """One PartStatus per part number that has a record."""
    repository.validate_repo(repo)
    index = record_files.cad_index(repo)
    with ThreadPoolExecutor(max_workers=2) as pool:      # two independent git calls: do them at the same time
        locks_job = pool.submit(lfs_locks.get_locks, repo)
        modified_job = pool.submit(repository.get_modified, repo)
        locks, modified = locks_job.result(), modified_job.result()

    rows = []
    for pn in record_store.list_pns(repo):
        revisions = index.get(pn, {})
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            rows.append(PartStatus(pn, "", "", f"Unreadable record: {e}", "error",
                                   files=sorted(f for fs in revisions.values() for f in fs), revisions=revisions))
            continue
        files = revisions.get(record.revision, [])
        every_file = [f for fs in revisions.values() for f in fs]

        # The record lock is the one that counts; fall back to any file lock.
        lock = locks.get(record_store.record_relpath(pn).lower())
        if lock is None:
            lock = next((locks[f.lower()] for f in files if f.lower() in locks), None)
        changed = any(f.lower() in modified for f in every_file)
        not_downloaded = any(read_only.is_pointer(Path(repo) / f) for f in files)
        owner = lock[1] if lock else ""

        if record.status == record_model.STATUS_VOID:
            state, kind = "Void", "void"
        elif record.pending:
            from litterbox.workflows import signoff_slots
            state, kind = signoff_slots.describe_pending(record.pending), "pending"
        elif record.status == record_model.STATUS_RELEASED:
            if changed:
                state, kind = "Released, but its files were modified", "stray"
            else:
                state, kind = "Released", "released"
        elif lock and lock[0] == "you":
            state, kind = "Checked out by you" + (" (modified)" if changed else ""), "mine"
        elif lock:
            state, kind = f"Checked out by {owner}", "theirs"
        elif changed:
            state, kind = "Modified but not checked out", "unclaimed"
        elif record.cots:
            state, kind = "COTS part", "cots"
        elif not files and every_file:
            others = ", ".join(sorted(revisions, key=revision_letters.revision_number))
            state, kind = f"No files for Rev {record.revision} (found Rev {others})", "stray"
        elif not files:
            state, kind = "Created, no CAD files yet", "ok"
        else:
            state, kind = "Available", "ok"

        if record.released_revision and record.status != record_model.STATUS_RELEASED:
            state += f" (Rev {record.released_revision} released)"
        outdated = any(record_lifecycle.references_need_update(record, rev, fs) for rev, fs in revisions.items())
        bom_outdated = any(record_lifecycle.bom_needs_update(record, rev, fs) for rev, fs in revisions.items())
        if outdated and kind not in ("error", "missing"):
            state += " (references need updating)"          # updating them counts the parts too
        elif bom_outdated and kind not in ("error", "missing"):
            state += " (BOM needs updating)"
        needed = tuple(record_exports.needed(record, step_pdf.possible_kinds(files)))
        if needed and kind not in ("error", "missing"):
            state += " (STEP/PDF needs updating)"
        if not_downloaded and kind != "void":
            state += " (not downloaded)"         # Check Out and Open download it; nothing else needs the files

        rows.append(PartStatus(pn, record.name, record.status, state, kind, owner, files,
                               record.description, record.cots, record.import_path,
                               record.revision, record.released_revision, revisions, outdated, record.pending,
                               not_downloaded, project=record.project, bom_outdated=bom_outdated,
                               released_revisions=released_revisions(record), files_needed=needed))
    return rows
