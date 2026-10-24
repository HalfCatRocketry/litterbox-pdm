"""
part_details_text.py - a part's Details tab: the revisions you can pick from, and what is known about one of them
(its state, release, sign-offs, ECO and files, and the part's purchasing information). The parts it uses are on the
Uses tab.
"""

from litterbox.exporting import step_pdf
from litterbox.gui.logic import history_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import material_text
from litterbox.gui.logic import purchasing_text
from litterbox.records import record_changes
from litterbox.records import record_configurations
from litterbox.records import record_exports
from litterbox.workflows import workflow_templates


def revision_choices(record, revisions):
    """The revisions the Details tab offers, newest first (the first is the default). `revisions` is
    {revision: [files]}."""
    return [row[0] for row in history_text.revision_rows(record, revisions)]


def approval_for(record, rev):
    """The last finished workflow of this revision (an entry of record.approvals), preferring a release; or None."""
    entries = [a for a in record.approvals if a.get("revision") == rev]
    releases = [a for a in entries if a.get("action") == workflow_templates.RELEASE]
    return (releases or entries or [None])[-1]


def eco_for(record, rev):
    """(ECO number, how it stands) for a revision, or (None, ""). A released revision shows the ECO it was
    released with; one waiting for sign-offs shows the open request's ECO."""
    approval = approval_for(record, rev)
    if approval and approval.get("eco"):
        label = workflow_templates.label_of(approval.get("action") or workflow_templates.RELEASE)
        return approval["eco"], f"{label} workflow, {approval.get('completed_at', '')[:10]}".rstrip(", ")
    released = [e for e in record.history if e.get("event") == "released" and e.get("revision") == rev]
    if released and released[-1].get("eco"):
        return released[-1]["eco"], "released with it"
    if record.pending and record.pending.get("revision") == rev and record.pending.get("eco"):
        return record.pending["eco"], "waiting for sign-offs"
    return None, ""


def change_rows(record, rev, local=True):
    """[(label, text)]: what the release of `rev` said changed, and the disposition of `rev`'s parts (given when a
    later revision was released, or when it was voided)."""
    rows = []
    changed = record_changes.changed_in(record, rev)
    if changed is not None:
        rows.append(("Changed", record_changes.changes_text(changed)))
    event = record_changes.disposition_event(record, rev)
    if event is not None:
        label = record_changes.DISPOSITION_LABEL.get(event.get("disposition"), str(event.get("disposition")))
        rows.append(("Disposition", f"{label} ({event.get('reason', '')}; by {event.get('by', '')} on "
                                    f"{history_text.to_display_time(event.get('at', ''), local)})"))
    return rows


def files_flagged(record, rev, revisions):
    """The STEP and/or PDF that revision `rev` still needs (the working revision, released and flagged)."""
    if record is None or rev != record.revision:
        return []
    return record_exports.needed(record, step_pdf.possible_kinds(revisions.get(rev, [])))


def bom_flagged(record, rev):
    """True when revision `rev` is the working revision, released, and its BOM file still needs saving."""
    return record is not None and rev == record.revision and record_exports.bom_flagged(record)


def files_made_text(record, rev, revisions, local=True):
    """What the Details tab says about the STEP and PDF Litterbox made for a revision ("" if it made none and none
    are needed)."""
    entry = record.exports.get(rev, {})
    lines = []
    for kind in record_exports.KINDS:
        made = entry.get(kind)
        if made:
            lines.append(f"{record_exports.LABEL[kind]} made by {made.get('by', '')} on "
                         f"{history_text.to_display_time(made.get('at', ''), local)}")
    needed = files_flagged(record, rev, revisions)
    if needed:
        lines.insert(0, " and ".join(record_exports.LABEL[kind] for kind in needed)
                     + (" need" if len(needed) > 1 else " needs") + " updating")
    return "; ".join(lines)


def revision_details(record, rev, revisions, local=True, currency=None):
    """[(label, text)] for the Details tab with revision `rev` picked. `revisions` is {revision: [files]};
    `currency` is the team's (core/currency.py), for the unit cost."""
    rows = {row[0]: row for row in history_text.revision_rows(record, revisions)}
    state = rows[rev][1] if rev in rows else ""
    fields = [("Part", str(record.pn)), ("Name", record.name)]
    if record.description:
        fields.append(("Description", record.description))
    if record.project:
        fields.append(("Project", record.project))
    fields.append(("Revision", f"Rev {rev}" + (" (working)" if rev == record.revision else "")))
    fields.append(("State", state))
    released = [e for e in record.history if e.get("event") == "released" and e.get("revision") == rev]
    if released:
        event = released[-1]
        fields.append(("Released", f"by {event.get('by', '')} on {history_text.to_display_time(event.get('at', ''), local)}"
                                   + (" (Admin override)" if event.get("override") else "")))
    approval = approval_for(record, rev)
    if approval:
        if approval.get("template_name"):
            label = workflow_templates.label_of(approval.get("action") or workflow_templates.RELEASE)
            fields.append(("Workflow", f"{label} {approval['template_name']}"))
        signed = [s.get("by", "") + (f" (superuser, for {s['for']})" if s.get("for") else "")
                  for s in approval.get("signoffs", [])]
        if signed:
            fields.append(("Signed off by", ", ".join(signed)))
    number, how = eco_for(record, rev)
    fields.append(("ECO", f"{number} ({how})" if number else "None"))
    fields += change_rows(record, rev, local)
    files = revisions.get(rev, [])
    fields.append(("Files", list_view.file_types(files) if files else "No files"))
    material = material_text.details_text(record, rev, files)
    if material is not None:
        fields.append(("Material", material))
    configurations = configurations_text(record, rev)
    if configurations:
        fields.append(("Configurations", configurations))
    made = files_made_text(record, rev, revisions, local)
    if made:
        fields.append(("STEP/PDF", made))
    fields.append(("Created", f"by {record.created_by} on {history_text.to_display_time(record.created_at, local)}"))
    if record.cots:
        fields.append(("COTS", "Yes (a purchased part)"))
    fields += purchasing_text.details_rows(record.purchasing, currency)
    if record.import_path:
        fields.append(("Imported from", record.import_path))
    return fields


def configurations_text(record, rev):
    """The Details tab's line about a model's configurations (records/record_configurations.py): only for one with
    more than one, since those are revised and released together. "" otherwise, or if they haven't been read."""
    names = record_configurations.names(record, rev)
    if len(names) < 2:
        return ""
    return f"{len(names)}: {', '.join(names)}. They are all released together"
