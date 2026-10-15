"""
workflow_responses.py - the other answers to a request: reject (by a signer), withdraw (by whoever asked)
and reassign a slot to someone else.
"""

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_store
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_templates


def _each(repo, pns, edit_for, action_name, message):
    """Apply a change to every part of a batch that still has a request (parts already dealt with are skipped),
    with one download and one upload."""
    failed, items = {}, []
    for pn in workflow_request.as_pns(pns):
        try:
            record = record_store.load(repo, pn)
        except (LitterboxError, record_model.RegistryError) as e:
            failed[pn] = str(e)
            continue
        if record.pending:
            items.append((pn, action_name, edit_for(record.pending.get("id")), message.replace("{pn}", str(pn))))
    done = []
    if items:
        batch = batch_core.edit_records(repo, items)
        done = list(batch.results)
        failed.update({pn: str(e) for pn, e in batch.errors.items()})
        if batch.notice:
            diagnostics.LOG(batch.notice)
    return workflow_signoff.report(done, failed)


@converts_errors
def reject(repo, pns, comment):
    """Send a pending batch back. A person named to sign (or an Admin) may; a comment is required. The parts are
    free to check out again."""
    me = workflow_request.current_member(repo, "signoff")
    comment = " ".join((comment or "").split())
    if not comment:
        raise workflow_templates.WorkflowError("Say why you are rejecting it, so the person who asked knows what to fix.")

    def edit_for(batch_id):
        def edit(record, user):
            pending = workflow_request.pending_of(record, batch_id)
            if not (signoff_slots.is_signer(pending, me) or signoff_slots.is_admin(me)):
                raise record_model.RegistryError("Only a person named to sign this (or an Admin) can reject it.")
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_REJECTED, user, action=pending["action"],
                               reason=comment, requested_by=pending.get("requested_by"),
                               signed=[e.get("by") for e in pending["signoffs"]] or None)
            record.pending = {}
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request rejected - " + comment)


@converts_errors
def withdraw(repo, pns, reason=""):
    """Cancel a pending batch. The person who asked, or an Admin, may."""
    me = workflow_request.current_member(repo, "signoff")
    reason = " ".join((reason or "").split())

    def edit_for(batch_id):
        def edit(record, user):
            pending = workflow_request.pending_of(record, batch_id)
            if not (pending.get("requested_by_id") == me.id or signoff_slots.is_admin(me)):
                raise record_model.RegistryError("Only the person who asked, or an Admin, can withdraw the request.")
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_WITHDRAWN, user, action=pending["action"],
                               reason=reason or None, requested_by=pending.get("requested_by"))
            record.pending = {}
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request withdrawn")


@converts_errors
def reassign(repo, pns, slot, person_id):
    """Name a different person for a sign-off that hasn't been given. The person who asked, or an Admin, may."""
    me = workflow_request.current_member(repo, "signoff")
    directory = team_store.load(repo)

    def edit_for(batch_id):
        def edit(record, user):
            pending = workflow_request.pending_of(record, batch_id)
            if not (pending.get("requested_by_id") == me.id or signoff_slots.is_admin(me)):
                raise record_model.RegistryError("Only the person who asked, or an Admin, can change who signs.")
            if not 0 <= slot < len(pending["slots"]):
                raise record_model.RegistryError("That sign-off isn't in the request. Run Get Latest.")
            if signoff_slots.slot_done(pending, slot):
                raise record_model.RegistryError("That sign-off has already been given.")
            old = pending["slots"][slot]
            new = signoff_slots.make_slot(directory, old["roles"], person_id, f"the {' or '.join(old['roles'])} sign-off",
                        bool(old.get("extra")))
            template = pending["template"]
            ids = [s["id"] for i, s in enumerate(pending["slots"]) if i != slot] + [new["id"]]
            if not template.get("allow_same_person", False) and len(set(ids)) != len(ids):
                raise record_model.RegistryError("This workflow doesn't let one person fill more than one sign-off.")
            if not template.get("requester_may_sign", True) and new["id"] == pending.get("requested_by_id"):
                raise record_model.RegistryError("This workflow doesn't let the person who asked sign.")
            pending["slots"][slot] = new
            record_lifecycle.add_event(record, record_model.EVENT_REASSIGNED, user, action=pending["action"],
                               roles=[" or ".join(new["roles"])], reason=f"{old['name']} replaced by {new['name']}")
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: signer changed")
