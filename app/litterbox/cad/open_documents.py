"""
open_documents.py - what a CAD program has open, in a form that is the same for every program: one OpenDocument per
file, compared by key(path), and the Change between two looks (a program's watcher, cad/cad_program.py).
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OpenDocument:
    path: str                   # as the program gives it
    unsaved: bool               # it has changes that are not saved yet
    read_only: bool             # the program opened it read-only
    visible: bool               # shown in a window (False: loaded as part of an assembly)


def key(path):
    """A path in the form used to compare paths: absolute, and on Windows lower case with backslashes."""
    return os.path.normcase(os.path.abspath(str(path)))


class Change:
    """One difference between two snapshots: what happened to which file."""
    OPENED, CLOSED, MODIFIED, SAVED = "opened", "closed", "has unsaved changes", "saved"

    def __init__(self, what, document):
        self.what = what
        self.document = document

    @property
    def key(self):
        return key(self.document.path)

    def __repr__(self):
        return f"Change({self.what!r}, {self.document.path!r})"


def differences(old, new):
    """[Change] between two snapshots ({key(path): OpenDocument}), in a steady order."""
    changes = []
    for k in sorted(set(old) | set(new)):
        before, after = old.get(k), new.get(k)
        if before is None:
            changes.append(Change(Change.OPENED, after))
        elif after is None:
            changes.append(Change(Change.CLOSED, before))
        elif after.unsaved and not before.unsaved:
            changes.append(Change(Change.MODIFIED, after))
        elif before.unsaved and not after.unsaved:
            changes.append(Change(Change.SAVED, after))
    return changes
