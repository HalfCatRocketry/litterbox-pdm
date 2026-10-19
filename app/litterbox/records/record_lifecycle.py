"""
record_lifecycle.py - the status rules, applied to a record in memory: check out, check in, release,
Make COTS, edit details, reopen (Unrelease), void.

in_work -> released -> (reopen) in_work, and in_work -> void. Each change adds a history event. Saving the record
and the git work are up to the caller.
"""

from litterbox.core.revision_letters import FIRST_REVISION, revision_number
from litterbox.records import record_model


def add_event(record, event, by, **details):
    """Append an event to the record's history and return it."""
    by = (by or "").strip()
    if not by:
        raise record_model.RegistryError("An event must say who did it.")
    entry = {"event": event, "by": by, "at": record_model.now_utc(), "revision": record.revision}
    entry.update({key: value for key, value in details.items() if value is not None})
    record.history.append(entry)
    return entry


def require_status(record, wanted, action):
    if record.status != wanted:
        raise record_model.RegistryError(
            f"Cannot {action} {record.pn}: its status is '{record.status}', not '{wanted}'."
        )


def require_reason(reason, action):
    reason = (reason or "").strip()
    if not reason:
        raise record_model.RegistryError(f"A reason is required to {action}.")
    return reason


def require_not_pending(record, action):
    if record.pending:
        raise record_model.RegistryError(f"Cannot {action} {record.pn}: it is waiting for sign-offs. "
                            "Withdraw the request first.")


def record_checkout(record, by, files):
    """Log a check-out. Released, void and COTS parts can't be checked out."""
    require_status(record, record_model.STATUS_IN_WORK, "check out")
    require_not_pending(record, "check out")
    if record.cots:
        raise record_model.RegistryError(f"Cannot check out {record.pn}: it is a COTS (purchased) part.")
    return add_event(record, record_model.EVENT_CHECKED_OUT, by, files=list(files))


def set_references(record, stems, revision=None):
    """Remember which parts this revision's assembly uses (a list like ['HCR-00005-001_A'], possibly
    empty). Also clears the 'out of date' mark. Returns True if anything changed."""
    revision = revision or record.revision
    stems = sorted(set(stems), key=str.lower)
    changed = record.references.get(revision) != stems
    record.references[revision] = stems
    if revision in record.references_outdated:
        record.references_outdated.remove(revision)
        changed = True
    return changed


def references_need_update(record, revision, files):
    """True if the list of parts used by this revision of an assembly can't be trusted: it has an assembly
    file (in `files`) and either was never read or has changed since it was last read."""
    if record.cots or record.status == record_model.STATUS_VOID:
        return False
    if not any(str(f).lower().endswith(".sldasm") for f in files):
        return False
    return revision not in record.references or revision in record.references_outdated


def record_checkin(record, by, files, comment="", references=None):
    """Log a check-in. `references` (a list, or None for 'not read this time') updates what the
    working revision uses; the event lists them when they changed. If an assembly file was checked
    in and the references could not be read, the revision is marked as needing an update."""
    changed = set_references(record, references) if references is not None else False
    if references is None and any(str(f).lower().endswith(".sldasm") for f in files):
        if record.revision not in record.references_outdated:
            record.references_outdated.append(record.revision)
    return add_event(record, record_model.EVENT_CHECKED_IN, by, files=list(files),
                     comment=(comment or "").strip() or None,
                     references=list(record.references.get(record.revision, [])) if changed else None)


def mark_released(record, by, files, **details):
    """in_work -> released. `files` is the list of files being frozen. Extra details (who signed off, an
    override reason...) go on the history event. This does not look at a pending request: workflow.py,
    which owns those, clears it."""
    require_status(record, record_model.STATUS_IN_WORK, "release")
    if record.cots:
        raise record_model.RegistryError(f"Cannot release {record.pn}: it is a COTS (purchased) part.")
    record.status = record_model.STATUS_RELEASED
    record.released_revision = record.revision
    return add_event(record, record_model.EVENT_RELEASED, by, files=list(files), **details)


def edit_details(record, by, name, description):
    """Change the name and/or description. Returns the history entry, or None if nothing changed.

    The caller must hold the record's lock (the part is checked out). The history entry lists
    what changed, e.g. changes: ["name: 'Bracket' -> 'Bracket, left'"].
    """
    name = " ".join((name or "").split())
    description = " ".join((description or "").split())
    if not name:
        raise record_model.RegistryError("A name is required.")
    changes = []
    if name != record.name:
        changes.append(f"name: '{record.name}' -> '{name}'")
    if description != record.description:
        changes.append(f"description: '{record.description}' -> '{description}'")
    if not changes:
        return None
    record.name, record.description = name, description
    return add_event(record, record_model.EVENT_EDITED, by, changes=changes)


def change_project(record, by, project):
    """Move a part to another project ("" for none), because a project was changed or deleted. Returns the history
    entry, or None if it was already there. The caller must hold the record's lock."""
    project = " ".join((project or "").split())
    if project == record.project:
        return None
    entry = add_event(record, record_model.EVENT_EDITED, by,
                      changes=[f"project: '{record.project}' -> '{project}'"])
    record.project = project
    return entry


def mark_cots(record, by, files):
    """Turn an in-work part into a COTS (purchased) part. `files` is the list of files it covers."""
    require_status(record, record_model.STATUS_IN_WORK, "make COTS")
    require_not_pending(record, "make COTS")
    if record.cots:
        raise record_model.RegistryError(f"{record.pn} is already a COTS part.")
    if record.released_revision or record.revision != FIRST_REVISION:
        raise record_model.RegistryError(f"Cannot make {record.pn} COTS: it has been released or revised, so it is "
                            "not an unmodified purchased part.")
    record.cots = True
    return add_event(record, record_model.EVENT_MADE_COTS, by, files=list(files))


def _earlier_released_revision(record):
    """The latest revision released before the working one (empty if there was none)."""
    earlier = [e.get("revision") for e in record.history
               if e.get("event") == record_model.EVENT_RELEASED and e.get("revision") and e.get("revision") != record.revision]
    return max(earlier, key=revision_number, default="")


def mark_reopened(record, by, reason):
    """released -> in_work, or COTS -> a normal in-work part. A reason is required."""
    require_not_pending(record, "reopen")
    was_cots = record.status == record_model.STATUS_IN_WORK and record.cots
    if not was_cots:
        require_status(record, record_model.STATUS_RELEASED, "reopen")
    reason = require_reason(reason, "reopen a part")
    record.status = record_model.STATUS_IN_WORK
    if not was_cots:
        record.released_revision = _earlier_released_revision(record)
    record.cots = False
    return add_event(record, record_model.EVENT_REOPENED, by, reason=reason, was_cots=True if was_cots else None)


def mark_void(record, by, reason):
    """in_work -> void. The number stays used forever. A reason is required.

    Only a part that has never been released can be voided. Once a revision has been released
    the part can't disappear: an unwanted new revision is cancelled instead."""
    require_status(record, record_model.STATUS_IN_WORK, "void")
    require_not_pending(record, "void")
    if record.released_revision:
        raise record_model.RegistryError(f"Cannot void {record.pn}: Rev {record.released_revision} was released. "
                            "Use Cancel Revision to throw away the revision that is in work.")
    reason = require_reason(reason, "void a part")
    record.status = record_model.STATUS_VOID
    return add_event(record, record_model.EVENT_VOIDED, by, reason=reason)
