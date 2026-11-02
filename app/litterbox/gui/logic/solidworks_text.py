"""
solidworks_text.py - what the window does with what SolidWorks has open (see cad/solidworks/sw_watcher.py): which
of a set of vault files are open or unsaved, the questions and warnings about them, making open documents
writable after a check-out (cad/solidworks/sw_reload.py), and Refresh Read State.
"""

import os
from pathlib import PurePosixPath

from litterbox.core import file_types
from litterbox.cad import open_documents


def _by_key(repo, rels):
    return {open_documents.key(f"{repo}/{rel}"): rel for rel in rels}


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


def writable_plan(found, repo, changed):
    """After a check-out, split the documents SolidWorks has open read-only (OpenDocuments, `found`) into
    (switch, reload, ask), lists of SolidWorks' own paths: `switch` are made writable where they are; `reload` are
    those the check-out downloaded a newer version of (`changed`, relative to the vault), loaded again; `ask` are the
    ones to reload that have unsaved changes, which reloading would lose."""
    newer = {open_documents.key(f"{repo}/{rel}") for rel in changed}
    switch = [doc.path for doc in found if open_documents.key(doc.path) not in newer]
    reload = [doc.path for doc in found if open_documents.key(doc.path) in newer]
    ask = [doc.path for doc in found if doc.unsaved and open_documents.key(doc.path) in newer]
    return switch, reload, ask


def _file_names(paths):
    return ", ".join(file_types.file_name(path) for path in paths)


def reload_unsaved_question(paths):
    """Before reloading documents with unsaved changes after a check-out."""
    return (f"You checked these out, and the vault had a newer version, but SolidWorks has them open with changes "
            f"that are not saved:\n\n  {_file_names(paths)}\n\nReload them as writable now? Your unsaved changes "
            "will be lost. No leaves them open read-only: save your changes somewhere else, then reload them.")


def writable_done_text(paths):
    """The status line after open documents were made writable."""
    return f"{_file_names(paths)} {'is' if len(paths) == 1 else 'are'} now writable in SolidWorks"


def writable_failed_text(failed):
    """The status line when some couldn't be made writable: [(path, why)]."""
    return (f"Couldn't make {_file_names([path for path, _why in failed])} writable in SolidWorks: in SolidWorks, "
            "use File > Reload with Read-only unticked")


def in_vault(repo, path):
    """True if this full path is a file inside the vault."""
    return open_documents.key(path).startswith(open_documents.key(repo) + os.sep)


def read_state_plan(found, writable, stale):
    """Refresh Read State: make each open vault document (OpenDocuments, `found`) match its file on disk
    (`writable`: {key(path): True if the file may be written}; a document with no entry is left alone). Returns
    (switch, reload, ask, lock), lists of the program's own paths: `switch` are made writable where they are;
    `reload` are those a check-out downloaded a newer version of while they were open (`stale`: keys), loaded again
    so the old copy can't be saved over the new one; `ask` are the ones to reload that have unsaved changes; `lock`
    are made read-only, because their file is."""
    switch, reload, ask, lock = [], [], [], []
    for doc in found:
        key = open_documents.key(doc.path)
        if key not in writable:
            continue
        if writable[key] and doc.read_only:
            (reload if key in stale else switch).append(doc.path)
            if key in stale and doc.unsaved:
                ask.append(doc.path)
        elif not writable[key] and not doc.read_only:
            lock.append(doc.path)
    return switch, reload, ask, lock


def read_only_done_text(paths, unsaved):
    """The status line after open documents were made read-only (`unsaved`: those with unsaved changes)."""
    text = f"{_file_names(paths)} {'is' if len(paths) == 1 else 'are'} now read-only in SolidWorks"
    if unsaved:
        text += f" (to keep the unsaved changes in {_file_names(unsaved)}, use Save As)"
    return text


def read_only_failed_text(failed):
    """The status line when some couldn't be made read-only: [(path, why)]."""
    return (f"Couldn't make {_file_names([path for path, _why in failed])} read-only in SolidWorks: in SolidWorks, "
            "use File > Reload with Read-only ticked")


def read_state_unchanged_text(running):
    """The status line when Refresh Read State had nothing to do."""
    if not running:
        return "SolidWorks isn't running"
    return "Everything this vault has open in SolidWorks is already read-only or writable as it should be"


def still_old(repo, changed, done):
    """The files the check-out updated (relative to the vault) that weren't just reloaded (`done`: full paths)."""
    reloaded = {open_documents.key(path) for path in done}
    return [rel for rel in changed if open_documents.key(f"{repo}/{rel}") not in reloaded]


def queued_part_notes(changes, repo, busy, files_of):
    """Warnings for parts waiting to be checked in (busy: {part number text: what the job does}) that SolidWorks
    just opened or saved. files_of(part number text) -> that part's files. Returns [text]."""
    notes = []
    for pn, label in sorted(busy.items()):
        keys = _by_key(repo, files_of(pn))
        for change in changes:
            if change.key not in keys or change.what not in (open_documents.Change.OPENED, open_documents.Change.SAVED):
                continue
            verb = "opened" if change.what == open_documents.Change.OPENED else "saved"
            notes.append(f"{PurePosixPath(keys[change.key]).name} was {verb} in SolidWorks while Litterbox is still "
                         f"working on {pn} ({label.lower()}). Wait until the banner says Ready before changing it.")
    return notes
