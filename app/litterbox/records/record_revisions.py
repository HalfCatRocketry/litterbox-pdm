"""
record_revisions.py - revising a released part to its next letter, and cancelling a revision before it
is released (cancelled letters are never reused).
"""

from litterbox.core.revision_letters import next_revision, revision_number
from litterbox.records import record_lifecycle
from litterbox.records import record_model


def cancelled_revisions(record):
    """Revision letters that were cancelled. They are never used again."""
    return [e["cancelled"] for e in record.history
            if e.get("event") == record_model.EVENT_REVISION_CANCELLED and e.get("cancelled")]


def next_free_revision(record):
    """The letter a revise would use: the one after the working revision, skipping cancelled ones."""
    return next_revision(record.revision, skip=cancelled_revisions(record))


def can_revise(record):
    """'' if the part can be revised, else the reason it can't."""
    if record.pending:
        return "It is waiting for sign-offs."
    if record.cots:
        return "It is a COTS (purchased) part, which is never revised."
    if record.status != record_model.STATUS_RELEASED:
        return f"Its status is '{record.status}'. Only a released part can be revised."
    return ""


def mark_revised(record, by, reason, files):
    """released -> a new working revision (in_work). `files` are the new revision's files."""
    problem = can_revise(record)
    if problem:
        raise record_model.RegistryError(f"Cannot revise {record.pn}. {problem}")
    reason = record_lifecycle.require_reason(reason, "revise a part")
    previous = record.revision
    record.revision = next_free_revision(record)
    if previous in record.references:                   # the copy uses the same parts the original did
        record.references[record.revision] = list(record.references[previous])
        if previous in record.references_outdated:
            record.references_outdated.append(record.revision)
    if previous in record.quantities:
        record.quantities[record.revision] = dict(record.quantities[previous])
    if previous in record.bom_items:                    # lines added by hand to the BOM carry on too
        record.bom_items[record.revision] = dict(record.bom_items[previous])
    if previous in record.documents:                    # and so do linked documents
        record.documents[record.revision] = list(record.documents[previous])
    record.status = record_model.STATUS_IN_WORK
    return record_lifecycle.add_event(record, record_model.EVENT_REVISED, by, from_revision=previous, reason=reason, files=list(files))


def can_cancel_revision(record):
    """'' if the working revision can be cancelled, else the reason it can't."""
    if record.status != record_model.STATUS_IN_WORK:
        return f"Its status is '{record.status}'. Only a revision that is still in work can be cancelled."
    if not record.released_revision:
        return f"Rev {record.revision} was never released, so there is no earlier revision to go back to. Use Void."
    if revision_number(record.released_revision) >= revision_number(record.revision):
        return "The working revision is the released one. Use Unrelease instead."
    return ""


def mark_revision_cancelled(record, by, reason, files):
    """in_work revision -> gone; the part goes back to its latest released revision.
    `files` are the names the cancelled revision's files were kept under."""
    record_lifecycle.require_not_pending(record, "cancel the revision of")
    problem = can_cancel_revision(record)
    if problem:
        raise record_model.RegistryError(f"Cannot cancel the revision of {record.pn}. {problem}")
    reason = record_lifecycle.require_reason(reason, "cancel a revision")
    cancelled = record.revision
    record.references.pop(cancelled, None)
    record.quantities.pop(cancelled, None)
    record.bom_items.pop(cancelled, None)
    record.documents.pop(cancelled, None)
    if cancelled in record.references_outdated:
        record.references_outdated.remove(cancelled)
    record.revision = record.released_revision
    record.status = record_model.STATUS_RELEASED
    return record_lifecycle.add_event(record, record_model.EVENT_REVISION_CANCELLED, by, cancelled=cancelled, reason=reason, files=list(files))
