"""
part_details_text.py - a part's Details tab: the revisions you can pick from, and what is known about one of them
(its state, release, sign-offs, ECO and files, and the part's purchasing information). The parts it uses are on the
Uses tab.
"""

from litterbox.gui.logic import history_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import purchasing_text
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


def revision_details(record, rev, revisions, local=True):
    """[(label, text)] for the Details tab with revision `rev` picked. `revisions` is {revision: [files]}."""
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
    files = revisions.get(rev, [])
    fields.append(("Files", list_view.file_types(files) if files else "No files"))
    fields.append(("Created", f"by {record.created_by} on {history_text.to_display_time(record.created_at, local)}"))
    if record.cots:
        fields.append(("COTS", "Yes (a purchased part)"))
    fields += purchasing_text.details_rows(record.purchasing)
    if record.import_path:
        fields.append(("Imported from", record.import_path))
    return fields
