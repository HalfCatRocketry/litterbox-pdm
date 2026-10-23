"""
lifecycle.py - Release, Make COTS, Unrelease (reopen) and Void, for one
part or many. Each only edits the part's record, under a short lock.
"""

from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import planning
from litterbox.records import record_changes
from litterbox.records import record_lifecycle
from litterbox.records.error_conversion import converts_errors


def _refuse_if_workflow(repo, action, pns):
    """An action that has workflow templates must go through them, so it can't be done directly. Documents have
    templates of their own (workflow_templates.for_targets)."""
    from litterbox.workflows import workflow_store
    from litterbox.workflows import workflow_templates
    action = workflow_templates.for_targets(action, pns)
    if workflow_store.has_templates(repo, action):
        raise LitterboxError(f"{workflow_templates.label_of(action)} in this vault needs sign-offs. Use the Workflow window "
                             "to ask for them; it happens when everyone required has signed.")


@converts_errors
def release(repo, pn):
    """Freeze a part and its drawing. Call release_plan() first and get the user to confirm.

    Returns the list of files that were released.
    """
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "release", [pn])
    plan = planning.release_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be released yet:\n- " + "\n- ".join(plan.problems))
    batch_core.edit_record(
        repo, pn, "release",
        lambda record, user: record_lifecycle.mark_released(record, user, plan.files),
        f"{pn}: Released",
    )
    return plan.files


@converts_errors
def make_cots(repo, pn):
    """Record an existing part as COTS (purchased): it can no longer be checked out.
    Call make_cots_plan() first and get the user to confirm. Returns the files it covers."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "make_cots", [pn])
    plan = planning.make_cots_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be made COTS yet:\n- " + "\n- ".join(plan.problems))
    batch_core.edit_record(
        repo, pn, "make_cots",
        lambda record, user: record_lifecycle.mark_cots(record, user, plan.files),
        f"{pn}: Made COTS",
    )
    return plan.files


@converts_errors
def reopen(repo, pn, reason):
    """Make a released part editable again. A reason is required."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "reopen", [pn])
    batch_core.edit_record(
        repo, pn, "reopen",
        lambda record, user: record_lifecycle.mark_reopened(record, user, reason),
        f"{pn}: Unreleased - {batch_core.one_line(reason)}",
    )


@converts_errors
def void(repo, pn, reason):
    """Abandon a part. Its number is never reused. A reason is required."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "void", [pn])
    batch_core.edit_record(
        repo, pn, "void",
        lambda record, user: record_lifecycle.mark_void(record, user, reason),
        f"{pn}: Voided - {batch_core.one_line(reason)}",
    )


def _plan_batch(repo, plans, action, verb, change, message):
    """Do `change(record, user, plan)` on every part whose plan is ok, in one go. Returns (done, failed)."""
    batch, items, by_pn = batch_core.Batch(), [], {}
    for plan in plans:
        if plan.ok:
            by_pn[plan.pn] = plan
            items.append((plan.pn, action,
                          lambda record, user, plan=plan: change(record, user, plan), message.format(pn=plan.pn)))
        else:
            batch.errors[plan.pn] = LitterboxError(f"{plan.pn} can't be {verb} yet:\n- " + "\n- ".join(plan.problems))
    if items:
        edited = batch_core.edit_records(repo, items)
        batch.results = {pn: by_pn[pn].files for pn in edited.results}
        batch.errors.update(edited.errors)
        batch.notice = edited.notice
    return batch_core.as_lists(batch, [plan.pn for plan in plans])


def _released(record, user, files, change):
    """Release, recording what changed and the earlier revision's disposition (records/record_changes.py)."""
    earlier = record_changes.earlier_revision(record.revision, record.released_revision)
    wanted = record_changes.wanted(record.pn, "release", record.revision, record.released_revision)
    change = record_changes.clean(change, *wanted, where=f"{record.pn}: ") if change is not None else {}
    record_lifecycle.mark_released(record, user, files, changed=change.get("changed"))
    if earlier and change.get("disposition"):
        record_changes.record_disposition(record, user, change["disposition"], earlier,
                                          f"Rev {record.revision} released")


def _voided(record, user, reason, change):
    """Void, recording the voided revision's disposition."""
    wanted = record_changes.wanted(record.pn, "void", record.revision, record.released_revision)
    change = record_changes.clean(change, *wanted, where=f"{record.pn}: ") if change is not None else {}
    record_lifecycle.mark_void(record, user, reason)
    if change.get("disposition"):
        record_changes.record_disposition(record, user, change["disposition"], record.revision, "voided")


@converts_errors
def release_many(repo, pns, changes=None):
    """release() for several parts with one download and one upload. Call release_plans() first and get the user
    to confirm. `changes` is {part number text: {"changed", "disposition"}} for parts at Rev B or later (see
    records/record_changes.py); when given, every disposition asked for is required. Returns (done, failed): done
    is [(pn, released files)]."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "release", pns)
    return _plan_batch(repo, planning.release_plans(repo, pns), "release", "released",
                       lambda record, user, plan: _released(record, user, plan.files, _change(changes, record)),
                       "{pn}: Released")


def _change(changes, record):
    return None if changes is None else (changes.get(str(record.pn)) or {})


@converts_errors
def make_cots_many(repo, pns):
    """make_cots() for several parts with one download and one upload."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "make_cots", pns)
    return _plan_batch(repo, planning.make_cots_plans(repo, pns), "make_cots", "made COTS",
                       lambda record, user, plan: record_lifecycle.mark_cots(record, user, plan.files), "{pn}: Made COTS")


def _reason_batch(repo, pns, action, change, message):
    """`message(pn)` is each part's commit message."""
    batch = batch_core.edit_records(repo, [(pn, action, change, message(pn)) for pn in pns])
    batch.results = dict.fromkeys(batch.results)
    return batch_core.as_lists(batch, pns)


@converts_errors
def reopen_many(repo, pns, reason):
    """reopen() (Unrelease) for several parts with one download and one upload; one reason for all of them."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "reopen", pns)
    return _reason_batch(repo, pns, "reopen", lambda record, user: record_lifecycle.mark_reopened(record, user, reason),
                         lambda pn: f"{pn}: Unreleased - {batch_core.one_line(reason)}")


@converts_errors
def void_many(repo, pns, reason, changes=None):
    """void() for several parts with one download and one upload; one reason for all of them. `changes` is {part
    number text: {"disposition"}}: what to do with the parts already made (required for each part when given)."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "void", pns)
    return _reason_batch(repo, pns, "void",
                         lambda record, user: _voided(record, user, reason, _change(changes, record)),
                         lambda pn: f"{pn}: Voided - {batch_core.one_line(reason)}")
