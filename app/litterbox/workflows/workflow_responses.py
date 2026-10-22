"""
workflow_responses.py - the other answers to a request: reject (by a signer: it becomes a draft for whoever asked
to change, see workflow_drafts.py), withdraw (by whoever asked, also a draft), reassign a slot to someone else (by
whoever asked), and hand over your own sign-offs to someone else (by the person named).
"""

from litterbox import diagnostics
from litterbox.change_orders import eco_model
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_store
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_drafts
from litterbox.workflows import workflow_ecos
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_templates


def _each(repo, pns, edit_for, action_name, message, ecos=None, drafts=False):
    """Apply a change to every part of a batch that still has a request (parts already dealt with are skipped),
    with one download and one upload. `ecos` (an EcoCloser or EcoNoter) deals with the requests' ECOs. With
    drafts=True, parts whose request is a draft take the change too."""
    failed, items = {}, []
    for pn in workflow_request.as_pns(pns):
        try:
            record = record_store.load(repo, pn)
        except (LitterboxError, record_model.RegistryError) as e:
            failed[pn] = str(e)
            continue
        found = record.pending or (record.draft if drafts else None)
        if found:
            items.append((pn, action_name, edit_for(found.get("id")), message.replace("{pn}", str(pn))))
    done = []
    if items:
        batch = batch_core.edit_records(repo, items, finish=ecos.finish if ecos is not None else None)
        done = list(batch.results)
        failed.update({pn: str(e) for pn, e in batch.errors.items()})
        if batch.notice:
            diagnostics.LOG(batch.notice)
    return workflow_signoff.report(done, failed)


@converts_errors
def reject(repo, pns, comment, override=False):
    """Send a pending batch back to whoever asked. A person named to sign (or an Admin) may; a comment is
    required. It becomes a draft (workflow_drafts.py): the parts are free to check out again, and whoever asked
    changes and resubmits it or withdraws it. Its ECO stays open, with the rejection in its history.
    override=True is an Admin's Override Reject, recorded as an Admin override."""
    me = workflow_request.current_member(repo, "override_release" if override else "signoff")
    comment = " ".join((comment or "").split())
    if not comment:
        raise workflow_templates.WorkflowError("Say why you are rejecting it, so the person who asked knows what to fix.")

    ecos = workflow_ecos.EcoNoter(repo, "rejected", comment)

    def edit_for(batch_id):
        def edit(record, user):
            pending = workflow_request.pending_of(record, batch_id)
            if not (signoff_slots.is_signer(pending, me) or signoff_slots.is_admin(me)):
                raise record_model.RegistryError("Only a person named to sign this (or an Admin) can reject it.")
            ecos.note(pending)
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_REJECTED, user, action=pending["action"],
                               reason=comment, override=True if override else None,
                               requested_by=pending.get("requested_by"),
                               requested_by_id=pending.get("requested_by_id"),
                               signed=[e.get("by") for e in pending["signoffs"]] or None,
                               signed_ids=[e["id"] for e in pending["signoffs"] if e.get("id")] or None)
            workflow_drafts.make_draft(record, pending, user, comment, override)
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request rejected" + (" (Admin override)" if override else "")
                 + " - " + comment, ecos)


@converts_errors
def withdraw(repo, pns, reason=""):
    """Cancel a pending batch, or a rejected one waiting to be changed (a draft). The person who asked, or an
    Admin, may. Its ECO is closed as withdrawn."""
    me = workflow_request.current_member(repo, "signoff")
    reason = " ".join((reason or "").split())

    ecos = workflow_ecos.EcoCloser(repo, eco_model.WITHDRAWN, reason)

    def edit_for(batch_id):
        def edit(record, user):
            if record.pending:
                request = workflow_request.pending_of(record, batch_id)
            elif record.draft and record.draft.get("id") == batch_id:
                request = record.draft
            else:
                raise record_model.RegistryError(f"{record.pn} is now in a different request. Run Get Latest.")
            if not (request.get("requested_by_id") == me.id or signoff_slots.is_admin(me)):
                raise record_model.RegistryError("Only the person who asked, or an Admin, can withdraw the request.")
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_WITHDRAWN, user, action=request["action"],
                               reason=reason or None, requested_by=request.get("requested_by"),
                               requested_by_id=request.get("requested_by_id"))
            record.pending, record.draft = {}, {}
            ecos.note(request)
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request withdrawn", ecos, drafts=True)


def _new_slot(directory, pending, slot, person_id, me):
    """The slot `slot` of a request named for `person_id` instead, checked against the request's rules."""
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
        raise record_model.RegistryError(f"This workflow doesn't let one person fill more than one sign-off, and "
                                         f"{new['name']} already has one.")
    if not template.get("requester_may_sign", True) and new["id"] == pending.get("requested_by_id"):
        raise record_model.RegistryError("This workflow doesn't let the person who asked sign.")
    return old, new


def _swap(record, user, pending, slot, old, new, handed_over=False):
    pending["slots"][slot] = new
    record_lifecycle.add_event(record, record_model.EVENT_REASSIGNED, user, action=pending["action"],
                               roles=[" or ".join(new["roles"])], reason=f"{old['name']} replaced by {new['name']}",
                               from_id=old.get("id"), to_id=new.get("id"), handed_over=True if handed_over else None)


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
            old, new = _new_slot(directory, pending, slot, person_id, me)
            _swap(record, user, pending, slot, old, new)
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: signer changed")


@converts_errors
def hand_over(repo, pns, people):
    """Give some or all of your own sign-offs on a request to other people: `people` is {slot index: person id},
    for slots named for you that you haven't given. They then see it in their My Tasks."""
    me = workflow_request.current_member(repo, "signoff")
    directory = team_store.load(repo)
    if not people:
        raise workflow_templates.WorkflowError("Choose who should sign instead of you.")

    def edit_for(batch_id):
        def edit(record, user):
            pending = workflow_request.pending_of(record, batch_id)
            for slot, person_id in sorted(people.items()):
                if not (0 <= slot < len(pending["slots"])) or pending["slots"][slot].get("id") != me.id:
                    raise record_model.RegistryError("You can only hand over sign-offs named for you. Run Get Latest.")
                if person_id == me.id:
                    raise record_model.RegistryError("Choose someone other than yourself.")
                old, new = _new_slot(directory, pending, slot, person_id, me)
                _swap(record, user, pending, slot, old, new, handed_over=True)
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: sign-off handed over")
