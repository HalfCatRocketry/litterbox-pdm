"""
lifecycle.py - Release, Make COTS, Unrelease (reopen) and Void, for one
part or many. Each only edits the part's record, under a short lock.
"""

from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import planning
from litterbox.records import registry
from litterbox.records.error_conversion import converts_errors


def _refuse_if_workflow(repo, action):
    """An action that has workflow templates must go through them, so it can't be done directly."""
    from litterbox.workflows import workflow
    if workflow.has_templates(repo, action):
        raise LitterboxError(f"{workflow.label_of(action)} in this vault needs sign-offs. Use the Workflow window "
                             "to ask for them; it happens when everyone required has signed.")


@converts_errors
def release(repo, pn):
    """Freeze a part and its drawing. Call release_plan() first and get the user to confirm.

    Returns the list of files that were released.
    """
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "release")
    plan = planning.release_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be released yet:\n- " + "\n- ".join(plan.problems))
    batch_core.edit_record(
        repo, pn, "release",
        lambda record, user: registry.mark_released(record, user, plan.files),
        f"{pn}: Released",
    )
    return plan.files


@converts_errors
def make_cots(repo, pn):
    """Record an existing part as COTS (purchased): it can no longer be checked out.
    Call make_cots_plan() first and get the user to confirm. Returns the files it covers."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "make_cots")
    plan = planning.make_cots_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be made COTS yet:\n- " + "\n- ".join(plan.problems))
    batch_core.edit_record(
        repo, pn, "make_cots",
        lambda record, user: registry.mark_cots(record, user, plan.files),
        f"{pn}: Made COTS",
    )
    return plan.files


@converts_errors
def reopen(repo, pn, reason):
    """Make a released part editable again. A reason is required."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "reopen")
    batch_core.edit_record(
        repo, pn, "reopen",
        lambda record, user: registry.mark_reopened(record, user, reason),
        f"{pn}: Unreleased - {batch_core.one_line(reason)}",
    )


@converts_errors
def void(repo, pn, reason):
    """Abandon a part. Its number is never reused. A reason is required."""
    pn = batch_core.as_pn(pn)
    _refuse_if_workflow(repo, "void")
    batch_core.edit_record(
        repo, pn, "void",
        lambda record, user: registry.mark_void(record, user, reason),
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


@converts_errors
def release_many(repo, pns):
    """release() for several parts with one download and one upload. Call release_plans() first and get the user
    to confirm. Returns (done, failed): done is [(pn, released files)]."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "release")
    return _plan_batch(repo, planning.release_plans(repo, pns), "release", "released",
                       lambda record, user, plan: registry.mark_released(record, user, plan.files), "{pn}: Released")


@converts_errors
def make_cots_many(repo, pns):
    """make_cots() for several parts with one download and one upload."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "make_cots")
    return _plan_batch(repo, planning.make_cots_plans(repo, pns), "make_cots", "made COTS",
                       lambda record, user, plan: registry.mark_cots(record, user, plan.files), "{pn}: Made COTS")


def _reason_batch(repo, pns, action, change, message):
    """`message(pn)` is each part's commit message."""
    batch = batch_core.edit_records(repo, [(pn, action, change, message(pn)) for pn in pns])
    batch.results = {pn: None for pn in batch.results}
    return batch_core.as_lists(batch, pns)


@converts_errors
def reopen_many(repo, pns, reason):
    """reopen() (Unrelease) for several parts with one download and one upload; one reason for all of them."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "reopen")
    return _reason_batch(repo, pns, "reopen", lambda record, user: registry.mark_reopened(record, user, reason),
                         lambda pn: f"{pn}: Unreleased - {batch_core.one_line(reason)}")


@converts_errors
def void_many(repo, pns, reason):
    """void() for several parts with one download and one upload; one reason for all of them."""
    pns = batch_core.unique_pns(pns)
    _refuse_if_workflow(repo, "void")
    return _reason_batch(repo, pns, "void", lambda record, user: registry.mark_void(record, user, reason),
                         lambda pn: f"{pn}: Voided - {batch_core.one_line(reason)}")
