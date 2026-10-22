"""
document_details_text.py - a document's own Details window in words: what is known about one revision (its state,
release, sign-offs, ECO and files), the files of a revision, and the part revisions that link to it.
"""

from pathlib import PurePosixPath

from litterbox.gui.logic import document_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import part_details_text
from litterbox.records import record_model
from litterbox.workflows import workflow_templates

FILE_COLUMNS = (("name", "File", 300), ("type", "Type", 80))

LINKED_COLUMNS = (("pn", "Part", 120), ("name", "Name", 220), ("rev", "Rev", 50), ("state", "Status", 220))


def revision_details(record, rev, revisions, types_by_key, local=True):
    """[(label, text)] for the Details tab with revision `rev` picked. `revisions` is {revision: [files]}."""
    rows = {row[0]: row for row in history_text.revision_rows(record, revisions)}
    fields = [("Document", str(record.pn)), ("Title", record.name),
              ("Type", document_text.type_name(record.doc_type, types_by_key))]
    if record.description:
        fields.append(("Description", record.description))
    fields.append(("Revision", f"Rev {rev}" + (" (working)" if rev == record.revision else "")))
    fields.append(("State", rows[rev][1] if rev in rows else ""))
    released = [e for e in record.history if e.get("event") == record_model.EVENT_RELEASED and e.get("revision") == rev]
    if released:
        fields.append(("Released", f"by {released[-1].get('by', '')} on "
                                   f"{history_text.to_display_time(released[-1].get('at', ''), local)}"))
    approval = part_details_text.approval_for(record, rev)
    if approval:
        if approval.get("template_name"):
            label = workflow_templates.label_of(approval.get("action") or workflow_templates.RELEASE)
            fields.append(("Workflow", f"{label} {approval['template_name']}"))
        signed = [s.get("by", "") + (f" (superuser, for {s['for']})" if s.get("for") else "")
                  for s in approval.get("signoffs", [])]
        if signed:
            fields.append(("Signed off by", ", ".join(signed)))
    number, how = part_details_text.eco_for(record, rev)
    fields.append(("ECO", f"{number} ({how})" if number else "None"))
    files = revisions.get(rev, [])
    fields.append(("Files", list_view.file_types(files) if files else "No files"))
    fields.append(("Created", f"by {record.created_by} on {history_text.to_display_time(record.created_at, local)}"))
    return fields


def file_rows(revisions, rev):
    """[(vault path, (name, type))] for the Files tab: one revision's files."""
    return [(path, (PurePosixPath(path).name, PurePosixPath(path).suffix.lstrip(".").upper()))
            for path in sorted(revisions.get(rev, []))]


def linked_rows(links, rows_by_pn):
    """[(iid, values)] for the Where linked tab. `links` is [(PN, revision)] (documents/doc_links.where_linked);
    `rows_by_pn` gives each part's name and state."""
    found = []
    for pn, rev in links:
        row = rows_by_pn.get(pn)
        if row is None:
            state = "Not in the list: run Get Latest"
        elif rev == row.revision:
            state = row.state
        else:
            state = "Released (superseded)" if rev in getattr(row, "released_revisions", ()) else "Older revision"
        found.append((f"{pn}|{rev}", (str(pn), row.name if row else "", rev, state)))
    return found


def linked_note(links):
    """The line above the Where linked table."""
    if not links:
        return "No part links to this document."
    parts = len({pn for pn, _rev in links})
    return (f"Linked from {parts} part{'s' if parts != 1 else ''} "
            f"({len(links)} revision{'s' if len(links) != 1 else ''})")
