"""
record_lifecycle.py - the status rules, applied to a record in memory: check out, check in, release,
Make COTS, edit details, reopen (Unrelease), void.

in_work -> released -> (reopen) in_work, and in_work -> void. Each change adds a history event. Saving the record
and the git work are up to the caller.
"""

from litterbox.core import file_types
from litterbox.core.revision_letters import FIRST_REVISION, revision_number
from litterbox.records import purchasing_info
from litterbox.records import record_configurations
from litterbox.records import record_materials
from litterbox.records import record_model
from litterbox.records import record_other_files
from litterbox.util import person_name


def add_event(record, event, by, **details):
    """Append an event to the record's history and return it. `by` is a name; one from repository.get_user also
    puts the person's team id in the event (by_id)."""
    by_id = person_name.id_of(by)
    by = (by or "").strip()
    if not by:
        raise record_model.RegistryError("An event must say who did it.")
    entry = {"event": event, "by": by, "at": record_model.now_utc(), "revision": record.revision}
    if by_id:
        entry["by_id"] = by_id
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
    if not any(file_types.is_assembly(f) for f in files):
        return False
    return revision not in record.references or revision in record.references_outdated


def set_quantities(record, counts, revision=None):
    """Remember how many of each part this revision's assembly uses ({stem: count}). Every part in its list of
    parts used gets a count, 0 if none was found (all its copies suppressed, say). Returns True if anything
    changed."""
    revision = revision or record.revision
    counts = {stem: int(n) for stem, n in counts.items()}
    for stem in record.references.get(revision, []):
        counts.setdefault(stem, 0)
    changed = record.quantities.get(revision) != counts
    record.quantities[revision] = counts
    return changed


def bom_needs_update(record, revision, files):
    """True if the quantities in this revision's BOM can't be trusted: it has an assembly file (in `files`) and
    its counts were never read, were lost when the assembly changed without SolidWorks to count it, or don't
    cover every part it uses (an older Litterbox checked it in)."""
    if record.cots or record.status == record_model.STATUS_VOID:
        return False
    if not any(file_types.is_assembly(f) for f in files):
        return False
    if references_need_update(record, revision, files) or revision not in record.quantities:
        return True
    counts = record.quantities[revision]
    return any(stem not in counts for stem in record.references.get(revision, []))


def material_needs_update(record, revision, files):
    """True if this revision has a part file (.SLDPRT, in `files`) whose material was never read, or was lost when the
    file changed without SolidWorks to read it (records/record_materials.py)."""
    if not record.uses_cad or record.status == record_model.STATUS_VOID:
        return False
    if not any(file_types.is_part(f) for f in files):
        return False
    return not record_materials.is_read(record, revision)


def record_checkin(record, by, files, comment="", references=None, quantities=None, material=None, other_files=None,
                   configurations=None):
    """Log a check-in. `references` (a list, or None for 'not read this time') updates what the
    working revision uses; the event lists them when they changed. If an assembly file was checked
    in and the references could not be read, the revision is marked as needing an update.
    `quantities` ({stem: count}, or None) are how many of each it uses; when an assembly file was checked in
    without them, the old counts are dropped, so its BOM shows that it needs updating. `material` (text, '' for none
    assigned, or None for 'not read') is the part's material; when a part file was checked in without it, the old
    one is dropped, so it shows that it needs updating. `other_files` ([{file, toolbox}], or None) are the files the
    assembly uses that aren't Litterbox parts (records/record_other_files.py); without them they are forgotten too.
    `configurations` ((own, used), or None) are the model's configurations (records/record_configurations.py);
    without them a checked-in model's are forgotten."""
    changed = set_references(record, references) if references is not None else False
    assembly = any(file_types.is_assembly(f) for f in files)
    if references is None and assembly:
        if record.revision not in record.references_outdated:
            record.references_outdated.append(record.revision)
    counted = False
    if quantities is not None:
        counted = set_quantities(record, quantities)
    elif assembly:
        record.quantities.pop(record.revision, None)
    if other_files is not None:
        record_other_files.set_other_files(record, other_files)
    elif assembly:
        record_other_files.forget(record)
    if configurations is not None:
        record_configurations.set_configurations(record, *configurations)
    elif any(file_types.is_part(f) or file_types.is_assembly(f) for f in files):
        record_configurations.forget(record)
    material_changed = False
    if material is not None:
        material_changed = record_materials.set_material(record, material)
    elif any(file_types.is_part(f) for f in files):
        record_materials.forget(record)
    return add_event(record, record_model.EVENT_CHECKED_IN, by, files=list(files),
                     comment=(comment or "").strip() or None,
                     references=list(record.references.get(record.revision, [])) if changed else None,
                     quantities=dict(record.quantities[record.revision]) if counted else None,
                     material=record_materials.material(record) if material_changed else None)


def mark_released(record, by, files, **details):
    """in_work -> released. `files` is the list of files being frozen. Extra details (who signed off, an
    override reason...) go on the history event. This does not look at a pending request: workflow.py,
    which owns those, clears it."""
    require_status(record, record_model.STATUS_IN_WORK, "release")
    if record.cots:
        raise record_model.RegistryError(f"Cannot release {record.pn}: it is a COTS (purchased) part.")
    record.status = record_model.STATUS_RELEASED
    record.released_revision = record.revision
    entry = {}
    if record.uses_cad:
        entry["wanted"] = True                  # its STEP and PDF are made again (record_exports.py)
    if record.references.get(record.revision) or record.bom_items.get(record.revision):
        entry["bom_wanted"] = True              # and its BOM file saved (parts/release_bom.py)
    if entry:
        record.exports[record.revision] = entry
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


def set_bom_item(record, by, stem, quantity):
    """Add a BOM line by hand to the working revision (or change its quantity), or with quantity None take it off.
    Returns the history entry, or None if nothing changed. The caller must hold the record's lock."""
    require_status(record, record_model.STATUS_IN_WORK, "change the BOM of")
    items = record.bom_items.setdefault(record.revision, {})
    before = items.get(stem)
    if before == quantity:
        return None
    if quantity is None:
        del items[stem]
        change = f"BOM: removed {stem}"
    else:
        items[stem] = quantity
        change = f"BOM: {stem} x {quantity}" + (f" (was {before})" if before is not None else " added")
    if not items:
        del record.bom_items[record.revision]
    return add_event(record, record_model.EVENT_EDITED, by, changes=[change])


def change_kind(record, by, kind, has_cad_files):
    """CAD <-> non-CAD. Only for a part never released, with no SolidWorks files in any revision
    (`has_cad_files`). Returns the history entry, or None if it was that kind already. The caller must hold the
    record's lock."""
    if kind not in record_model.ALL_KINDS:
        raise record_model.RegistryError(f"Unknown kind '{kind}'.")
    if kind == record.kind:
        return None
    label = record_model.KIND_LABEL
    if record.released_revision or record.status != record_model.STATUS_IN_WORK:
        raise record_model.RegistryError(f"{record.pn} has been released, so it stays {label[record.kind]}.")
    if record.cots:
        raise record_model.RegistryError(f"{record.pn} is a COTS part, which has a CAD model.")
    if has_cad_files:
        raise record_model.RegistryError(f"{record.pn} has SolidWorks files, so it stays {label[record.kind]}.")
    entry = add_event(record, record_model.EVENT_EDITED, by,
                      changes=[f"kind: {label[record.kind]} -> {label[kind]}"])
    record.kind = kind
    return entry


def edit_purchasing(record, by, fields):
    """Change the supplier, supplier part number, unit cost and lead time (`fields` is {name: text}; a field left
    out keeps its value, an empty one clears it). Returns the history entry, or None if nothing changed. Allowed in
    any status but void: purchasing information is not part of the design, so released and COTS parts take it too."""
    if record.status == record_model.STATUS_VOID:
        raise record_model.RegistryError(f"{record.pn} is void, so its purchasing information can't be changed.")
    wanted = dict(record.purchasing)
    wanted.update({key: value for key, value in fields.items() if key in purchasing_info.FIELDS})
    try:
        cleaned = purchasing_info.clean(wanted)
    except purchasing_info.PurchasingError as e:
        raise record_model.RegistryError(str(e))
    changes = purchasing_info.changes(record.purchasing, cleaned)
    if not changes:
        return None
    record.purchasing = cleaned
    return add_event(record, record_model.EVENT_PURCHASING_EDITED, by, changes=changes)


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
