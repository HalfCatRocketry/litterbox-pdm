"""
list_view.py - the parts list: filtering by search text and view, sorting naturally (part 2 before
part 10), the tick column, and row colours.
"""

import re
from pathlib import PurePosixPath


VIEWS = ("All", "Mine", "Checked out", "Released")


def filter_rows(rows, search="", view="All", show_void=False):
    """Pick which PartStatus rows to show.

    search      matches part number, name or description, ignoring capitals
    view        one of VIEWS
    show_void   void parts are hidden unless this is True
    """
    needle = (search or "").strip().lower()
    shown = []
    for row in rows:
        if row.kind == "void" and not show_void:
            continue
        if view == "Mine" and row.kind != "mine":
            continue
        if view == "Checked out" and row.kind not in ("mine", "theirs"):
            continue
        if view == "Released" and row.kind != "released" and not getattr(row, "released_revision", ""):
            continue
        if needle and not any(needle in text.lower() for text in
                              (str(row.pn), row.name, row.description, row.import_path)):
            continue
        shown.append(row)
    return shown


def _natural_key(text):
    """'HCR-10 b' sorts after 'HCR-9 b': numbers compare as numbers, words ignore capitals."""
    return [(0, int(piece), "") if piece.isdigit() else (1, 0, piece)
            for piece in re.split(r"(\d+)", text.lower()) if piece]


def sort_order(values, reverse=False):
    """Positions of `values` in sorted order. Blank values always come last."""
    texts = [str(value).strip() for value in values]
    filled = [i for i, text in enumerate(texts) if text]
    blank = [i for i, text in enumerate(texts) if not text]
    filled.sort(key=lambda i: _natural_key(texts[i]), reverse=reverse)
    return filled + blank


def file_types(files):
    """['cad/HCR-00001-001_A.SLDPRT', 'cad/HCR-00001-001_A.SLDDRW'] -> 'PRT, DRW'"""
    kinds = []
    for path in files:
        ext = PurePosixPath(path).suffix.lstrip(".").upper()
        if ext.startswith("SLD") and len(ext) > 3:
            ext = ext[3:]
        if ext and ext not in kinds:
            kinds.append(ext)
    return ", ".join(kinds)


TICK_ON, TICK_OFF = "\u2611", "\u2610"          # the box glyphs in the list's first column


def range_between(shown, anchor, iid):
    """Shift-click in a list with tick boxes: the rows from the last one clicked (`anchor`) to this one, in the
    order shown. Without a usable anchor it is just the clicked row."""
    if anchor in shown and iid in shown:
        a, b = sorted((shown.index(anchor), shown.index(iid)))
        return list(shown[a:b + 1])
    return [iid]


def shift_held(event):
    """True if the Shift key was down for a Tk mouse event."""
    return bool(getattr(event, "state", 0) & 0x1)


def tick_text(count):
    if not count:
        return "Nothing selected."
    return (f"{count} part{'s' if count != 1 else ''} selected. Check Out, Check In, Save Progress and Undo Checkout "
            "apply to the selected parts.")


def row_tags(kind, ticked):
    """The list row's tags: its colour, plus 'ticked' when its box is ticked."""
    return (kind, "ticked") if ticked else (kind,)
