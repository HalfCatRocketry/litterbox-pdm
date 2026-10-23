"""
list_view.py - the parts list: its views and filtering by search text, sorting naturally (part 2 before
part 10), the tick column, and row colours.
"""

import re
from pathlib import PurePosixPath

from litterbox.gui.logic import search_text


VIEWS = ("All", "Mine", "Checked out", "Released", "Not downloaded", "Void")


def in_view(row, view):
    """Does a part belong in a view (the sidebar's Parts entries)? Void parts show only in the Void view."""
    if view == "Void":
        return row.kind == "void"
    if row.kind == "void":
        return False
    if view == "Mine":
        return row.kind == "mine"
    if view == "Checked out":
        return row.kind in ("mine", "theirs")
    if view == "Released":
        return row.kind == "released" or bool(getattr(row, "released_revision", ""))
    if view == "Not downloaded":
        return bool(getattr(row, "not_downloaded", False))
    return True


def view_counts(rows):
    """{view: how many parts it has}, for the sidebar."""
    return {view: sum(1 for row in rows if in_view(row, view)) for view in VIEWS}


def default_search_values(row):
    return (str(row.pn), row.pn.short, row.name, row.description, row.import_path)


def filter_rows(rows, search="", view="All", values=None):
    """Pick which PartStatus rows to show.

    search      the search box's text (see search_text.py: plain text is "contains", * and ? are wildcards)
    view        one of VIEWS
    values      values(row) -> the texts to search in (the 'search in' box's columns); by default the part
                number, name, description and where it was imported from
    """
    return search_rows([row for row in rows if in_view(row, view)], search, values)


def search_rows(rows, search, values=None):
    """The rows that match the search text, whatever their view."""
    match = search_text.matcher(search)
    values = values or default_search_values
    return [row for row in rows if search_text.matches_any(match, values(row))]


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
        return "Nothing ticked."
    return (f"{count} part{'s' if count != 1 else ''} ticked. Check Out, Check In and the other changes act on "
            "the ticked parts.")


def row_tags(kind, ticked):
    """The list row's tags: its colour, plus 'ticked' when its box is ticked."""
    return (kind, "ticked") if ticked else (kind,)
