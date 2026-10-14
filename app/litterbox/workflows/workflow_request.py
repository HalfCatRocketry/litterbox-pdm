"""
workflow_request.py - asking for sign-off: checks that the parts can go through the action, names a
person for every slot, and stores the pending request in each part's record. Also the helpers the other steps
share (who you are on the team, a part's pending request, the files' fingerprints).
"""

import copy
import hashlib
import uuid
from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.parts import batch_core
from litterbox.parts import planning
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_identity
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates


def file_hashes(repo, files):
    """{file: sha256} for CAD files (paths relative to the vault)."""
    result = {}
    for rel in files:
        path = Path(repo) / rel
        if read_only.is_pointer(path):
            raise workflow_templates.WorkflowError(f"{rel} hasn't been downloaded. Run Get Latest.")
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as e:
            raise workflow_templates.WorkflowError(f"Could not read {rel}: {e}")
        result[rel] = digest.hexdigest()
    return result


def current_member(repo, action):
    """The current user as a team member. Workflows are about people, so a vault with no team can't use them."""
    identity = team_permissions.require(repo, action)
    if identity.state != team_identity.OK or identity.person is None:
        raise workflow_templates.WorkflowError("Set up the team first (Team... > Set Up Team): sign-offs are done by people on it.")
    return identity.person


def pending_of(record, batch_id=None):
    if not record.pending:
        raise workflow_templates.WorkflowError(f"{record.pn} has no request waiting for sign-offs. Run Get Latest in case it was "
                            "already dealt with.")
    if batch_id and record.pending.get("id") != batch_id:
        raise workflow_templates.WorkflowError(f"{record.pn} is now in a different request. Run Get Latest.")
    if record.pending.get("revision") != record.revision:
        raise workflow_templates.WorkflowError(f"The request for {record.pn} is for Rev {record.pending.get('revision')}, which is no "
                            "longer the working revision. Withdraw it.")
    return record.pending


def check_files_unchanged(repo, pending):
    if not pending.get("files"):
        return
    now = file_hashes(repo, list(pending["files"]))
    for rel, digest in pending["files"].items():
        if now.get(rel) != digest:
            raise workflow_templates.WorkflowError(f"{rel} is different from the file the sign-offs were asked for. Withdraw the "
                                "request and ask again. If you think your copy is behind, run Get Latest.")


def as_pns(pns):
    if not isinstance(pns, (list, tuple, set)):
        pns = [pns]
    return [batch_core.as_pn(p) for p in pns]


def _problems(repo, pn, action, reason, fetch, ctx=None):
    """(problems, files) for starting `action` on this part."""
    if action == workflow_templates.RELEASE:
        plan = planning.release_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    if action == workflow_templates.MAKE_COTS:
        plan = planning.make_cots_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    record = record_store.load(repo, pn)
    if record.pending:
        return ["It is already waiting for sign-offs."], []
    trial = copy.deepcopy(record)
    try:
        if action == workflow_templates.REOPEN:
            record_lifecycle.mark_reopened(trial, "check", reason or "check")
        else:
            record_lifecycle.mark_void(trial, "check", reason or "check")
    except record_model.RegistryError as e:
        return [str(e)], []
    return [], []


@converts_errors
def request(repo, pns, action, template_name, assignments, extras=(), reason=""):
    """Start a workflow on one or more parts: check every part first (nothing happens if any can't go ahead),
    then record the request in each. Returns the new request's id."""
    pns = as_pns(pns)
    if action not in workflow_templates.ACTIONS:
        raise workflow_templates.WorkflowError(f"'{action}' can't have a workflow.")
    me = current_member(repo, action)
    template = workflow_store.templates_for(repo, action).get(template_name)
    if template is None:
        raise workflow_templates.WorkflowError(f"There is no {workflow_templates.label_of(action)} workflow called '{template_name}'. Run Get Latest.")
    directory = team_store.load(repo)
    slots = signoff_slots.build_slots(template, directory, me.id, assignments, extras)
    reason = " ".join((reason or "").split())
    if action in workflow_templates.NEEDS_REASON and not reason:
        raise workflow_templates.WorkflowError(f"A reason is required to {workflow_templates.label_of(action).lower()} a part.")
    if not pns:
        raise workflow_templates.WorkflowError("Choose at least one part.")

    problems, files, ctx = {}, {}, planning.PlanContext(repo)         # the vault is looked at once for all the parts
    for pn in pns:
        found, cad = _problems(repo, pn, action, reason, True, ctx)
        if found:
            problems[pn] = found
        files[pn] = cad
    if problems:
        raise workflow_templates.WorkflowError("These can't go ahead yet:\n\n" + "\n".join(
            f"{pn}:\n  - " + "\n  - ".join(found) for pn, found in problems.items()))
    hashes = {pn: file_hashes(repo, files[pn]) for pn in pns}

    batch_id = uuid.uuid4().hex[:8]
    items = []
    for pn in pns:
        def edit(record, user, pn=pn):
            if record.pending:
                raise record_model.RegistryError(f"{record.pn} already has a request waiting for sign-offs.")
            if action == workflow_templates.RELEASE and (record.status != record_model.STATUS_IN_WORK or record.cots):
                raise record_model.RegistryError(f"Cannot release {record.pn}: its status is '{record.status}'.")
            record.pending = {
                "id": batch_id, "action": action, "revision": record.revision, "requested_by": user,
                "requested_by_id": me.id, "requested_at": record_model.now_utc(), "template_name": template.name,
                "template": template.to_dict(), "parts": [str(p) for p in pns], "slots": copy.deepcopy(slots),
                "files": dict(hashes[pn]), "signoffs": [],
                **({"reason": reason} if reason else {}),
            }
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_REQUESTED, user, action=action,
                               waiting_on=signoff_slots.waiting_on(record.pending), files=list(files[pn]) or None,
                               reason=reason or None)
        items.append((pn, action, edit, f"{pn}: {workflow_templates.label_of(action)} requested"))
    try:
        batch = batch_core.edit_records(repo, items, atomic=True)      # all or nothing: one download, one upload
    except (LitterboxError, record_model.RegistryError) as e:
        raise workflow_templates.WorkflowError(f"Could not start the workflow, so nothing was changed:\n\n{e}")
    if batch.notice:
        diagnostics.LOG(batch.notice)
    return batch_id
