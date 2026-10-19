"""
workflow_signoff.py - signing, and what happens when the last person signs: Release, Unrelease and
Void happen at once; Make COTS waits for the button again (complete). An Admin can override with a recorded
reason.
"""

from dataclasses import dataclass, field

from litterbox import diagnostics
from litterbox.change_orders import eco_model
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import planning
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.util import person_name
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_ecos
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_templates


@dataclass
class SignResult:
    signed: list = field(default_factory=list)       # parts you signed on
    completed: list = field(default_factory=list)    # parts where the action went through
    errors: dict = field(default_factory=dict)       # {pn: why} for parts where something failed
    summary: str = ""


@converts_errors
def sign_off(repo, pns, comment=""):
    """Approve, as the person named, every sign-off waiting for you on these parts. When a part then has all its
    sign-offs, release / reopen / void happens straight away; if that fails the sign-off is still saved.
    All the parts are signed with one download and one upload, and finished together."""
    pns = workflow_request.as_pns(pns)
    me = workflow_request.current_member(repo, "signoff")
    comment = " ".join((comment or "").split())
    result = SignResult()
    items = []
    for pn in pns:
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            result.errors[pn] = str(e)
            continue
        if not record.pending or not signoff_slots.open_slots(record.pending, me.id):
            continue                                            # nothing left for you here (or already done)

        def edit(record, user, batch_id=record.pending.get("id")):
            pending = workflow_request.pending_of(record, batch_id)
            mine = signoff_slots.open_slots(pending, me.id)
            if not mine:
                raise record_model.RegistryError(f"You have nothing left to sign on {record.pn}.")
            workflow_request.check_files_unchanged(repo, pending)
            for index in mine:
                pending["signoffs"].append({"slot": index, "by": user, "id": me.id, "roles": pending["slots"][index]
                                            ["roles"], "at": record_model.now_utc(),
                                            **({"comment": comment} if comment else {})})
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_SIGNED, user, action=pending["action"],
                               roles=[" or ".join(pending["slots"][i]["roles"]) for i in mine],
                               comment=comment or None, waiting_on=signoff_slots.waiting_on(pending) or None)

        items.append((pn, "signoff", edit, f"{pn}: signed off"))
    if items:
        batch = batch_core.edit_records(repo, items)
        result.signed = list(batch.results)
        result.errors.update({pn: str(e) for pn, e in batch.errors.items()})
        if batch.notice:
            diagnostics.LOG(batch.notice)

    finishing = []
    for pn in result.signed:
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            result.errors[pn] = str(e)
            continue
        if record.pending and signoff_slots.is_complete(record.pending) and record.pending["action"] in workflow_templates.AUTO_COMPLETE:
            finishing.append(pn)
    if finishing:
        try:
            done, failed, _files = _finish_many(repo, finishing)
        except LitterboxError as e:
            failed, done = {pn: e for pn in finishing}, []
        result.completed = done
        result.errors.update({pn: str(e) for pn, e in failed.items()})
    if not result.signed and not result.errors:
        raise workflow_templates.WorkflowError("There was nothing for you to sign on these parts. Run Get Latest.")
    if not result.signed and result.errors:
        raise workflow_templates.WorkflowError("\n".join(f"{pn}: {why}" for pn, why in result.errors.items()))
    result.summary = f"Signed off {len(result.signed)} part{'s' if len(result.signed) != 1 else ''}"
    return result


def _approval_entry(pending, completed_by, override=None, files=None, action=None, reason=None):
    entry = {"action": action, "revision": pending.get("revision") if pending else None}
    if pending:
        entry.update({"requested_by": pending.get("requested_by"), "requested_by_id": pending.get("requested_by_id"),
                      "requested_at": pending.get("requested_at"),
                      "template_name": pending.get("template_name"), "template": pending.get("template"),
                      "slots": pending.get("slots"), "signoffs": list(pending.get("signoffs", [])),
                      "files": dict(pending.get("files", {})), "parts": pending.get("parts"),
                      "eco": pending.get("eco")})
    else:
        entry.update({"signoffs": [], "files": dict(files or {})})
    if reason:
        entry["reason"] = reason
    person_name.stamp(entry, "completed_by", completed_by)
    entry["completed_at"] = record_model.now_utc()
    if override:
        entry["override"] = override
    return {k: v for k, v in entry.items() if v is not None}


def _finish_edit(repo, action, plan, override_reason, ecos=None):
    """The change that does the action on a record. Shared by complete() and override()."""
    def edit(record, user):
        pending = record.pending or None
        if override_reason is None:
            pending = workflow_request.pending_of(record)
            if not signoff_slots.is_complete(pending):
                raise record_model.RegistryError("Still waiting for: " + ", ".join(signoff_slots.waiting_on(pending)) + ".")
            workflow_request.check_files_unchanged(repo, pending)
        act = pending["action"] if pending else action
        reason = (pending or {}).get("reason") or override_reason
        signed = [e.get("by") for e in (pending or {}).get("signoffs", [])]
        signed_ids = [e.get("id") for e in (pending or {}).get("signoffs", []) if e.get("id")]
        details, override = {"signoffs": signed or None, "signoff_ids": signed_ids or None,
                             "eco": (pending or {}).get("eco")}, None
        if override_reason is not None:
            missing = signoff_slots.waiting_on(pending) if pending else ["every sign-off"]
            override = person_name.stamp({}, "by", user)
            override.update(reason=override_reason, missing=missing)
            details.update(override=True, reason=override_reason)
        files = workflow_request.file_hashes(repo, plan.files) if (plan is not None and not pending) else None
        approval = _approval_entry(pending, user, override, files, act, reason)
        if ecos is not None:
            ecos.note(pending)                                 # its ECO is closed too
        record.pending = {}                                    # the checks in mark_* refuse a pending part
        if act == workflow_templates.RELEASE:
            record_lifecycle.mark_released(record, user, plan.files, **details)
        elif act == workflow_templates.MAKE_COTS:
            record_lifecycle.mark_cots(record, user, plan.files)
        elif act == workflow_templates.REOPEN:
            record_lifecycle.mark_reopened(record, user, reason)
        else:
            record_lifecycle.mark_void(record, user, reason)
        record.approvals.append(approval)
    return edit


def _finish_many(repo, pns, override_reason=None, override_action=None):
    """Do the action now on several parts, with one download and one upload (the vault is checked once).
    Returns (done, failed, files): done is [pn], failed is {pn: error}, files is {pn: [files released]}."""
    ctx, failed, items, files = planning.PlanContext(repo), {}, [], {}
    ecos = workflow_ecos.EcoCloser(repo, eco_model.RELEASED, override_reason or "")
    for pn in workflow_request.as_pns(pns):
        try:
            record0 = record_store.load(repo, pn)
            action = record0.pending.get("action") if record0.pending else override_action
            if action not in workflow_templates.ACTIONS:
                raise workflow_templates.WorkflowError(f"{pn} has no request to complete.")
            plan = None
            if action == workflow_templates.RELEASE:
                plan = planning.release_plan(repo, pn, allow_pending=True, ctx=ctx)
            elif action == workflow_templates.MAKE_COTS:
                plan = planning.make_cots_plan(repo, pn, allow_pending=True, ctx=ctx)
            if plan is not None and not plan.ok:
                what = "released" if action == workflow_templates.RELEASE else "made COTS"
                raise LitterboxError(f"{pn} can't be {what} yet:\n- " + "\n- ".join(plan.problems))
        except (LitterboxError, record_model.RegistryError) as e:
            failed[pn] = e
            continue
        message = f"{pn}: {workflow_templates.label_of(action)} done" + (" (Admin override)" if override_reason is not None
                                                      else " after sign-offs")
        items.append((pn, action, _finish_edit(repo, action, plan, override_reason, ecos), message))
        files[pn] = list(plan.files) if plan is not None else []
    done = []
    if items:
        batch = batch_core.edit_records(repo, items, finish=ecos.finish)
        done = list(batch.results)
        failed.update(batch.errors)
        if batch.notice:
            diagnostics.LOG(batch.notice)
    return done, failed, files


def report(done, failed):
    if failed:
        raise workflow_templates.WorkflowError(("Done on " + ", ".join(map(str, done)) + ".\n\n" if done else "") +
                            "\n".join(f"{pn}: {why}" for pn, why in failed.items()))
    return done


@converts_errors
def complete(repo, pn):
    """Do the action for a part whose request has every sign-off."""
    workflow_request.current_member(repo, "signoff")
    done, failed, files = _finish_many(repo, [pn])
    if failed:
        raise next(iter(failed.values()))
    return files[done[0]]


@converts_errors
def complete_many(repo, pns):
    """Do the action for each part whose request has every sign-off, with one download and one upload. Carries on
    past a failure and reports every one at the end."""
    workflow_request.current_member(repo, "signoff")
    done, failed, _files = _finish_many(repo, pns)
    return report(done, {pn: str(e) for pn, e in failed.items()})


@converts_errors
def override(repo, pns, reason, action=None):
    """Admins only: do the action without the sign-offs. A reason is required and is recorded as an override.
    `action` is needed only for a part that has no request."""
    pns = workflow_request.as_pns(pns)
    workflow_request.current_member(repo, "override_release")
    reason = " ".join((reason or "").split())
    if not reason:
        raise workflow_templates.WorkflowError("A reason is required to go ahead without sign-offs.")
    done, failed, _files = _finish_many(repo, pns, override_reason=reason, override_action=action)
    return report(done, {pn: str(e) for pn, e in failed.items()})
