"""
workflow_drafts.py - a rejected request, being changed by whoever asked (a draft).

Rejecting a request (workflow_responses.reject) moves it from each part's `pending` to its `draft`, with who
rejected it, when and why (`rejected`). It leaves every signer's My Tasks and appears in the requester's, who can:

    change it and resubmit   workflow_request.resubmit: the same request id and ECO, every sign-off from the start;
                             parts taken out of it leave the draft (leaving_items)
    withdraw it              workflow_responses.withdraw: the draft is dropped and its ECO closed as withdrawn

While it is a draft its parts can be checked out and in like any other (nothing is waiting for sign-offs), but
they can't go into another workflow or action (parts/planning.draft_problem).
"""

import copy
from dataclasses import dataclass

from litterbox.parts import batch_core
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.util import person_name
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_templates


TAKEN_OUT = "Taken out of the workflow when it was resubmitted"


@dataclass
class Draft:
    id: str
    action: str
    eco: str                # its ECO number, "" for none
    parts: list             # [PN] that are in it now
    requested_by_id: str


def make_draft(record, pending, user, comment, override=False):
    """Turn the part's request into a draft: rejected by `user` with `comment`. The request is cleared."""
    draft = copy.deepcopy(pending)
    rejected = person_name.stamp({}, "by", user) | {"at": record_model.now_utc(), "comment": comment}
    if override:
        rejected["override"] = True
    draft["rejected"] = rejected
    record.draft = draft
    record.pending = {}


def find(repo, draft_id, me):
    """The draft with this id, from its parts' records. Only the person who asked (or an Admin) may change it.
    Raises WorkflowError."""
    parts, first = [], None
    for pn in record_store.list_pns(repo) + record_store.list_docs(repo):
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError:
            continue
        if record.draft and record.draft.get("id") == draft_id:
            parts.append(pn)
            first = first or record.draft
    if first is None:
        raise workflow_templates.WorkflowError("That rejected request isn't waiting to be changed any more. Run Get "
                                               "Latest in case it was resubmitted or withdrawn.")
    if not (first.get("requested_by_id") == me.id or signoff_slots.is_admin(me)):
        raise workflow_templates.WorkflowError("Only the person who asked, or an Admin, can change a rejected request.")
    return Draft(draft_id, first.get("action", ""), first.get("eco", ""), parts, first.get("requested_by_id", ""))


def leaving_items(draft, pns):
    """Batch-core items that take the draft off the parts no longer in it."""
    keep = {str(pn) for pn in pns}
    items = []
    for pn in draft.parts:
        if str(pn) in keep:
            continue

        def edit(record, user):
            if record.draft.get("id") != draft.id:
                return
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_WITHDRAWN, user,
                                       action=record.draft.get("action"), reason=TAKEN_OUT,
                                       requested_by=record.draft.get("requested_by"),
                                       requested_by_id=record.draft.get("requested_by_id"))
            record.draft = {}
        items.append((batch_core.as_pn(pn), draft.action, edit, f"{pn}: taken out of a resubmitted workflow"))
    return items
