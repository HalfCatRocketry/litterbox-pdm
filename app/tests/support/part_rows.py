"""Ready-made parts-list rows (PartStatus) for the window-logic tests. No tests here."""

from litterbox.parts.part_status import PartStatus
from litterbox.core.part_number import PN


def row(base, state="Available", kind="ok", description="", files=(), name="", import_path=""):
    return PartStatus(PN("HCR", base, 1), name or description, "in_work", state, kind, files=list(files),
                      description=description if name else "", import_path=import_path)


ROWS = [
    row(1, "Available", "ok", "Front upright"),
    row(2, "Checked out by you", "mine", "Rear upright"),
    row(3, "Checked out by Alex", "theirs", "Brake bracket"),
    row(4, "Released", "released", "Pedal"),
    row(5, "Void", "void", "Scrapped idea"),
    row(6, "Modified but not checked out", "stray", "Mystery"),
]


BY_PN = {r.pn: r for r in ROWS}


def revised(base, working, released, revisions, status="in_work", released_revisions=None):
    """A part row with several revisions, e.g. revised(7, "B", "A", {"A": [...], "B": [...]}). `released_revisions`
    is every revision released (oldest first); by default just `released`."""
    if released_revisions is None:
        released_revisions = (released,) if released else ()
    r = PartStatus(PN("HCR", base, 1), "Part", status, "Available", "ok", files=list(revisions.get(working, [])),
                   revision=working, released_revision=released, revisions=revisions,
                   released_revisions=tuple(released_revisions))
    return r
