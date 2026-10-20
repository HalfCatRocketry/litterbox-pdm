"""
purchasing_text.py - the Purchasing Info window's decisions and words: checking what was typed, what the Details
tab shows, and what the status line says afterwards (see records/purchasing_info.py and parts/purchasing.py).
"""

from litterbox.parts import purchasing
from litterbox.records import purchasing_info


def dialog_result(old, typed):
    """(problem, fields) for what was typed into the window ({field: text}). `problem` is text to show ("" if all
    is well); `fields` is what to save, or None when nothing changed."""
    try:
        cleaned = purchasing_info.clean(dict(old or {}, **typed))
    except purchasing_info.PurchasingError as e:
        return str(e), None
    if not purchasing_info.changes(old or {}, cleaned):
        return "", None
    return "", {key: purchasing_info.shown(cleaned, key) for key in purchasing_info.FIELDS}


def details_rows(section):
    """[(label, text)] for the Details tab: only the fields that are filled in."""
    return [(purchasing_info.LABELS[key], purchasing_info.shown(section, key))
            for key in purchasing_info.FIELDS if purchasing_info.shown(section, key)]


def done_text(pn, outcome):
    """The status line after Purchasing Info."""
    if outcome == purchasing.SAVED_LOCALLY:
        return f"Updated the purchasing info of {pn}. Save Progress or Check In to upload it."
    if outcome == purchasing.UNCHANGED:
        return f"The purchasing info of {pn} was already like that."
    return f"Updated the purchasing info of {pn}."
