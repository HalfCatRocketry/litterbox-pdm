"""
solidworks_text.py - what the window does with what SolidWorks has open (see cad/solidworks/sw_watcher.py): which
of a set of vault files are open or unsaved, and the questions and warnings about them.
"""

from pathlib import PurePosixPath

from litterbox.cad.solidworks import sw_documents
from litterbox.cad.solidworks import sw_watcher


def _by_key(repo, rels):
    return {sw_documents.key(f"{repo}/{rel}"): rel for rel in rels}


def open_among(snapshot, repo, rels):
    """The files (relative to the vault) among `rels` that SolidWorks has open."""
    keys = _by_key(repo, rels)
    return sorted(rel for k, rel in keys.items() if k in snapshot)


def unsaved_among(snapshot, repo, rels):
    """The files among `rels` that are open in SolidWorks with changes that are not saved yet."""
    keys = _by_key(repo, rels)
    return sorted(rel for k, rel in keys.items() if k in snapshot and snapshot[k].unsaved)


def _names(rels, limit=12):
    names = [PurePosixPath(rel).name for rel in rels]
    return "\n  ".join(names[:limit]) + (f"\n  ...and {len(names) - limit} more" if len(names) > limit else "")


def save_first_question(rels, action="check in"):
    """Before Check In / Save Progress: these have unsaved changes in SolidWorks."""
    return (f"These have changes in SolidWorks that are not saved yet:\n\n  {_names(rels)}\n\n"
            f"Litterbox uploads what is saved on disk. Save them in SolidWorks first, then {action}.\n\n"
            f"{action.capitalize()} anyway, without those changes?")


def may_be_replaced_question(rels):
    """Before Get Latest: these are open in SolidWorks and a download may replace them."""
    return (f"These files are open in SolidWorks:\n\n  {_names(rels)}\n\n"
            "Get Latest may download newer versions of them. SolidWorks would keep showing the old copy, and "
            "saving it would overwrite the new one. Close them in SolidWorks first.\n\nGet the latest anyway?")


def reopen_note(rels):
    """After a download: these were updated while open in SolidWorks."""
    return (f"These files were updated while they are open in SolidWorks:\n\n  {_names(rels)}\n\n"
            "Close and reopen them in SolidWorks so you aren't looking at an old copy.")


def queued_part_notes(changes, repo, busy, files_of):
    """Warnings for parts waiting to be checked in (busy: {part number text: what the job does}) that SolidWorks
    just opened or saved. files_of(part number text) -> that part's files. Returns [text]."""
    notes = []
    for pn, label in sorted(busy.items()):
        keys = _by_key(repo, files_of(pn))
        for change in changes:
            if change.key not in keys or change.what not in (sw_watcher.Change.OPENED, sw_watcher.Change.SAVED):
                continue
            verb = "opened" if change.what == sw_watcher.Change.OPENED else "saved"
            notes.append(f"{PurePosixPath(keys[change.key]).name} was {verb} in SolidWorks while Litterbox is still "
                         f"working on {pn} ({label.lower()}). Wait until the banner says Ready before changing it.")
    return notes
