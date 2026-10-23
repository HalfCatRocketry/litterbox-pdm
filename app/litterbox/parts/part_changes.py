"""
part_changes.py - what has changed in a checked-out part
(its change report), used before a check-in to spot a part with nothing to upload.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from litterbox import layout
from litterbox.core.doc_number import DocNumber
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.util import fast_yaml


def _record_edited_by_hand(repo, pn, user):
    """True if the PN record has changes beyond the 'checked out' entry Litterbox adds at check-out.

    Without this, fixing a typo in a record looks like "nothing changed" (only CAD
    files were compared), and the check-in would be treated as an undo and throw
    the fix away. A record that has been broken by a hand edit raises an error
    instead of returning False, so a broken edit is never silently discarded.
    """
    record_path = record_store.record_relpath(pn)
    try:
        head_text = runner.run(["git", "show", f"HEAD:{record_path}"], repo, quiet=True)
    except LitterboxError:
        return True                                   # not committed yet, so it is new
    try:
        committed = record_model.Record.from_dict(fast_yaml.safe_load(head_text))
    except yaml.YAMLError:
        return True

    current = record_store.load(repo, pn)                 # raises a clear error if the file is broken
    history = list(current.history)
    if history and history[-1].get("event") == record_model.EVENT_CHECKED_OUT and history[-1].get("by") == user:
        history = history[:-1]                        # the entry added by checkout() is expected
    current.history = history
    return current.to_dict() != committed.to_dict()


def gone_files(repo, pn, revision):
    """A document revision's files that are in the vault but were removed from your copy (Remove File): Check In
    uploads their removal and Undo Checkout puts them back. Parts' files are never removed this way: []."""
    if not isinstance(pn, DocNumber):
        return []
    return [rel for rel in repository.tracked(repo, f"{layout.DOC_DIR_NAME}/{pn}_{revision}.*")
            if not (Path(repo) / rel).exists()]


@dataclass
class ChangeReport:
    has_changes: bool           # anything at all to check in?
    changed_files: list         # CAD files with changes
    unchanged_files: list       # CAD files with no changes
    record_edited: bool         # the PN record was edited by hand
    unpushed: bool              # commits from an earlier failed attempt still need uploading


def build_change_report(repo, pn, user, cad=None, modified=None, unpushed_paths=None):
    """`cad`, `modified` and `unpushed_paths` (repository.paths_changed_in(repo, repository.UNPUSHED)) may be handed
    in when several parts are looked at together (they are read once)."""
    record_path = record_store.record_relpath(pn)
    if cad is None:
        cad = record_files.cad_files(repo, pn)
    if modified is None:
        modified = repository.get_modified(repo)
    if unpushed_paths is None:
        unpushed_paths = repository.paths_changed_in(repo, repository.UNPUSHED)
    changed = [f for f in cad if f.lower() in modified]
    record_edited = _record_edited_by_hand(repo, pn, user)
    unpushed = any(path in unpushed_paths for path in cad + [record_path])
    return ChangeReport(
        has_changes=bool(changed or record_edited or unpushed),
        changed_files=changed,
        unchanged_files=[f for f in cad if f not in changed],
        record_edited=record_edited,
        unpushed=unpushed,
    )


@converts_errors
def change_report(repo, pn):
    """What a check-in of this part would find. Changes nothing. The GUI uses it to
    warn before checking in a part that has no changes."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    return build_change_report(repo, pn, repository.get_user(repo))


@converts_errors
def change_reports(repo, pns):
    """change_report() for several parts, reading the vault's state once. Returns [(pn, ChangeReport)]."""
    repository.validate_repo(repo)
    user, modified, index = repository.get_user(repo), repository.get_modified(repo), record_files.cad_index(repo)
    unpushed = repository.paths_changed_in(repo, repository.UNPUSHED)
    reports = []
    for pn in batch_core.unique_pns(pns):
        cad = index.get(pn, {}).get(record_store.load(repo, pn).revision, [])
        reports.append((pn, build_change_report(repo, pn, user, cad, modified, unpushed)))
    return reports
