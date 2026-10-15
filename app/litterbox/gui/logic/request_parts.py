"""
request_parts.py - the parts in the Workflow window: which ones Add Parts can offer, and finding them by search.
"""

from litterbox.gui.logic import action_rules
from litterbox.gui.logic import list_view


def addable_rows(action, rows, current=(), busy=None):
    """The part rows (PartStatus) that could join a request for `action`: the kinds the action accepts, without
    parts already waiting for sign-offs, parts with a job in progress (`busy`, by part as text), or parts already
    in the request (`current`, PNs). Sorted by part number."""
    kinds = action_rules.ALLOWED_KINDS[action] - {"pending"}
    taken = {str(pn) for pn in current}
    busy = busy or {}
    found = [row for row in rows
             if row.kind in kinds and str(row.pn) not in taken and str(row.pn) not in busy]
    return [found[i] for i in list_view.sort_order([str(row.pn) for row in found])]


def search(rows, text):
    """The rows whose part number, name or description match `text` (all of them if it is empty)."""
    return list_view.filter_rows(rows, text, "All", show_void=True)
