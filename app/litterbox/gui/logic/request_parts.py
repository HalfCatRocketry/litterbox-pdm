"""
request_parts.py - the parts in the Workflow window: which ones Add Parts can offer, and finding them by search.
"""

from litterbox.core.doc_number import DocNumber
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import list_view
from litterbox.workflows import workflow_templates


def addable_rows(action, rows, current=(), busy=None, draft_id=None):
    """The part rows (PartStatus) that could join a request for `action`: the kinds the action accepts, without
    parts already waiting for sign-offs, parts in a rejected request being changed (but those of `draft_id`, the
    one being changed here), parts with a job in progress (`busy`, by part as text), or parts already in the
    request (`current`, PNs). Sorted by part number."""
    base = workflow_templates.base_action(action)
    if base not in action_rules.ALLOWED_KINDS:
        return []                                       # Remove document link: one part, chosen with its document
    kinds = action_rules.ALLOWED_KINDS[base] - {"pending"}
    documents = action in workflow_templates.DOC_ACTION.values()        # documents join documents, parts parts
    taken = {str(pn) for pn in current}
    busy = busy or {}
    found = [row for row in rows if row.kind in kinds and str(row.pn) not in taken and str(row.pn) not in busy
             and isinstance(row.pn, DocNumber) == documents
             and (getattr(row, "draft", None) or {}).get("id", draft_id) == draft_id]
    return [found[i] for i in list_view.sort_order([str(row.pn) for row in found])]


def search(rows, text):
    """The rows whose part number, name or description match `text` (all of them if it is empty)."""
    return list_view.search_rows(rows, text)
