"""
workflow_request.py - asking for sign-off: checks that the parts can go through the action, names a
person for every slot, and stores the pending request in each part's record. Also resubmitting a rejected request
(a draft), and the helpers the other steps share (who you are on the team, a part's pending request, the files'
fingerprints).
"""

import copy
import uuid
from pathlib import Path

from litterbox import diagnostics
from litterbox.change_orders import eco_store
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import planning
from litterbox.records import record_changes
from litterbox.records import record_lifecycle
from litterbox.records import record_links
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import project_access
from litterbox.team import team_identity
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.util import file_hash
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_drafts
from litterbox.workflows import workflow_ecos
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates


def file_hashes(repo, files):
    """{file: sha256} for CAD files (paths relative to the vault), downloaded or not."""
    result = {}
    for rel in files:
        path = Path(repo) / rel
        oid = lfs_download.pointer_oid(path)
        if oid is not None:                 # not downloaded: the pointer holds the file's SHA-256 already
            result[rel] = oid
            continue
        try:
            result[rel] = file_hash.sha256(path)
        except OSError as e:
            raise workflow_templates.WorkflowError(f"Could not read {rel}: {e}")
    return result


def current_member(repo, action):
    """The current user as a team member. Workflows are about people, so a vault with no team can't use them."""
    identity = team_permissions.require(repo, action)
    if identity.state != team_identity.OK or identity.person is None:
        raise workflow_templates.WorkflowError("Set up the team first (Team > Set Up Team): sign-offs are done by people on it.")
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


def _problems(repo, pn, action, reason, fetch, ctx=None, document=None):
    """(problems, files) for starting `action` on this part (or document)."""
    if action == workflow_templates.REMOVE_DOC:
        return _remove_problems(repo, pn, document, ctx), []
    action = workflow_templates.base_action(action)
    if action == workflow_templates.RELEASE:
        plan = planning.release_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    if action == workflow_templates.MAKE_COTS:
        plan = planning.make_cots_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    record = record_store.load(repo, pn)
    if record.pending:
        return ["It is already waiting for sign-offs."], []
    if _other_draft(record, ctx):
        return [planning.draft_problem(record)], []
    trial = copy.deepcopy(record)
    try:
        if action == workflow_templates.REOPEN:
            record_lifecycle.mark_reopened(trial, "check", reason or "check")
        else:
            record_lifecycle.mark_void(trial, "check", reason or "check")
    except record_model.RegistryError as e:
        return [str(e)], []
    return [], []


def _other_draft(record, ctx):
    """True if the part is in a draft other than the one being resubmitted."""
    return bool(record.draft) and record.draft.get("id") != getattr(ctx, "draft_ok", None)


def _remove_problems(repo, pn, document, ctx=None):
    """Why a document's link can't be taken off this part by a Remove document link request."""
    record = record_store.load(repo, pn)
    if record.pending:
        return ["It is already waiting for sign-offs."]
    if _other_draft(record, ctx):
        return [planning.draft_problem(record)]
    if not document or str(document) not in record_links.linked(record):
        return [f"{document or 'That document'} isn't linked to Rev {record.revision}."]
    if record.status != record_model.STATUS_RELEASED:
        return ["It isn't released: check it out and remove the link yourself."]
    return []


def change_for(record, action, changes):
    """What the request says changed on this part, and the disposition of the earlier revision's parts
    (records/record_changes.py), checked: {} when the action asks for neither. `changes` is {part number text:
    {"changed", "disposition"}}, or None when the caller doesn't give them (then nothing is required)."""
    asks = record_changes.wanted(record.pn, workflow_templates.base_action(action), record.revision,
                                 record.released_revision)
    if changes is None or not any(asks):
        return {}
    try:
        return record_changes.clean(changes.get(str(record.pn)), *asks, where=f"{record.pn}: ")
    except record_changes.ChangeError as e:
        raise workflow_templates.WorkflowError(str(e))


@converts_errors
def request(repo, pns, action, template_name, assignments, extras=(), reason="", eco=None, document=None,
            changes=None):
    """Start a workflow on one or more parts (or documents): check every one first (nothing happens if any can't
    go ahead), then record the request in each. Returns the new request's id. `document` is the document whose link
    a Remove document link request takes off.

    If the request needs an ECO (its template requires one, and it isn't a release of parts all at Rev A), `eco` is
    {"name", "description"} (its title and description): the ECO file is written in the same commit (see
    workflow_ecos.py and change_orders/), and each part's request names it. `changes` is {part number text:
    {"changed": [form, fit, function], "disposition": key}} for the parts that take them (a release of Rev B or
    later, a void; records/record_changes.py); when it is given, every disposition asked for is required.
    """
    return _ask(repo, pns, action, template_name, assignments, extras, reason, eco, document, changes)


@converts_errors
def resubmit(repo, draft_id, pns, action, template_name, assignments, extras=(), reason="", eco=None, document=None,
             changes=None):
    """Ask again for a rejected request (a draft, see workflow_drafts.py) as whoever asked has changed it: the same
    request id and the same ECO, with every sign-off starting again. Parts taken out of it leave the draft. Only the
    person who asked (or an Admin) may. Otherwise as request()."""
    return _ask(repo, pns, action, template_name, assignments, extras, reason, eco, document, changes,
                draft_id=draft_id)


def _ask(repo, pns, action, template_name, assignments, extras, reason, eco, document, changes, draft_id=None):
    pns = as_pns(pns)
    if action not in workflow_templates.ACTIONS:
        raise workflow_templates.WorkflowError(f"'{action}' can't have a workflow.")
    if action != workflow_templates.REMOVE_DOC and \
            workflow_templates.for_targets(workflow_templates.base_action(action), pns) != action:
        raise workflow_templates.WorkflowError(f"{workflow_templates.label_of(action)} is for "
                                               + ("documents." if action in workflow_templates.DOC_ACTION.values()
                                                  else "parts."))
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
    draft = workflow_drafts.find(repo, draft_id, me) if draft_id else None

    records = {pn: record_store.load(repo, pn) for pn in pns}
    try:
        project_access.require_parts(repo, pns, action)                 # a restricted project: its members ask,
        project_access.require_signers(repo, pns, [s["id"] for s in slots], directory)      # and sign
    except LitterboxError as e:
        raise workflow_templates.WorkflowError(str(e)) from None
    fields = workflow_ecos.eco_fields(template, eco, workflow_ecos.eco_needed(
        template, action, [r.revision for r in records.values()]))
    change = {pn: change_for(records[pn], action, changes) for pn in pns}
    problems, files = {}, {}
    ctx = planning.PlanContext(repo, draft_ok=draft_id)              # the vault is looked at once for all the parts
    for pn in pns:
        found, cad = _problems(repo, pn, action, reason, True, ctx, document)
        if found:
            problems[pn] = found
        files[pn] = cad
    if problems:
        raise workflow_templates.WorkflowError("These can't go ahead yet:\n\n" + "\n".join(
            f"{pn}:\n  - " + "\n  - ".join(found) for pn, found in problems.items()))
    hashes = {pn: file_hashes(repo, files[pn]) for pn in pns}

    batch_id = draft_id or uuid.uuid4().hex[:8]
    prepare, made = workflow_ecos.opener(
        repo, fields, action, template.name, batch_id,
        lambda: [(pn, record_store.load(repo, pn).revision, change[pn]) for pn in pns],      # read after the pull
        existing=draft.eco if draft else None)
    items = []
    for pn in pns:
        def edit(record, user, pn=pn):
            if record.pending:
                raise record_model.RegistryError(f"{record.pn} already has a request waiting for sign-offs.")
            if record.draft and record.draft.get("id") != draft_id:
                raise record_model.RegistryError(f"{record.pn}: {planning.draft_problem(record)}")
            if workflow_templates.base_action(action) == workflow_templates.RELEASE and (
                    record.status != record_model.STATUS_IN_WORK or record.cots):
                raise record_model.RegistryError(f"Cannot release {record.pn}: its status is '{record.status}'.")
            record.draft = {}
            record.pending = {
                "id": batch_id, "action": action, "revision": record.revision, "requested_by": user,
                "requested_by_id": me.id, "requested_at": record_model.now_utc(), "template_name": template.name,
                "template": template.to_dict(), "parts": [str(p) for p in pns], "slots": copy.deepcopy(slots),
                "files": dict(hashes[pn]), "signoffs": [],
                **({"reason": reason} if reason else {}),
                **({"eco": made["eco"]} if made.get("eco") else {}),
                **({"document": str(document)} if action == workflow_templates.REMOVE_DOC else {}),
                **({"change": dict(change[pn])} if change[pn] else {}),
            }
            record_lifecycle.add_event(record, record_model.EVENT_RELEASE_REQUESTED, user, action=action,
                               waiting_on=signoff_slots.waiting_on(record.pending), files=list(files[pn]) or None,
                               reason=reason or None, eco=made.get("eco"), resubmitted=True if draft else None,
                               changed=change[pn].get("changed"), disposition=change[pn].get("disposition"))
        items.append((pn, action, edit, f"{pn}: {workflow_templates.label_of(action)} "
                                        + ("resubmitted" if draft else "requested")))
    if draft:
        items += workflow_drafts.leaving_items(draft, pns)
    for attempt in range(1, 4):
        try:
            batch = batch_core.edit_records(repo, items, atomic=True, prepare=prepare)    # all or nothing
            break
        except (LitterboxError, record_model.RegistryError) as e:
            if made.get("new") and attempt < 3 and _eco_taken_upstream(repo, made.pop("eco")):
                made.pop("new", None)
                continue                        # someone took that ECO number a moment ago: use the next one
            raise workflow_templates.WorkflowError(f"Could not start the workflow, so nothing was changed:\n\n{e}")
    if batch.notice:
        diagnostics.LOG(batch.notice)
    return batch_id


def _eco_taken_upstream(repo, number):
    """True if the vault's latest commit (after a fetch) already has this ECO."""
    try:
        runner.run(["git", "fetch"], repo, quiet=True)
        runner.run(["git", "cat-file", "-e", f"@{{u}}:{eco_store.relpath(number)}"], repo, quiet=True)
        return True
    except LitterboxError:
        return False
