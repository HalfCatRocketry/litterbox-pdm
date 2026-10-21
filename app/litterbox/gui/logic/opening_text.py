"""
opening_text.py - what Open and Open Drawing offer for a part: which revisions, and what to say when
there is nothing to open.
"""

from pathlib import PurePosixPath

from litterbox.core import revision_letters
from litterbox.gui.logic import history_text


def open_choices(row, drawing=False):
    """[(revision, files)] that Open (or Open Drawing) can open for this part.

    Normally one. When the part has both a released revision and a different working revision
    with files, both are offered, working first, then any revisions released before those (newest first),
    and the user is asked which to open. With drawing=True only revisions that have a drawing are offered.
    """
    revisions = history_text.row_revisions(row)
    working = getattr(row, "revision", "A")
    released = getattr(row, "released_revision", "")
    wanted = []
    if revisions.get(working):
        wanted.append(working)
    if released and released != working and revisions.get(released):
        wanted.append(released)
    if not wanted and revisions:                       # fall back to the newest revision that has files
        wanted.append(max(revisions, key=revision_letters.revision_number))
    for rev in reversed(getattr(row, "released_revisions", ())):
        if rev not in wanted and revisions.get(rev):
            wanted.append(rev)
    choices = [(rev, revisions[rev]) for rev in wanted]
    if drawing:
        choices = [(rev, files) for rev, files in choices if _has_drawing(files)]
    return choices


def _has_drawing(files):
    return any(PurePosixPath(f).suffix.lower() == ".slddrw" for f in files)


def open_message(row, drawing=False):
    """Why a part's model (or drawing) can't be opened right now, or '' if it can."""
    if not any(history_text.row_revisions(row).values()):
        return f"{row.pn} has no CAD files yet."
    if drawing and not open_choices(row, drawing=True):
        return f"{row.pn} has no drawing."
    return ""
