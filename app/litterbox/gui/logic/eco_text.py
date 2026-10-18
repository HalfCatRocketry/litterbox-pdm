"""
eco_text.py - engineering change orders in words: the ECOs window's table and search, and one ECO's details.
"""

from litterbox.change_orders import eco_model
from litterbox.gui.logic import history_text
from litterbox.workflows import workflow_templates

STATUS_FILTERS = ("All",) + tuple(eco_model.STATUS_LABEL[s] for s in eco_model.STATUSES)

TABLE_COLUMNS = (("number", "ECO", 90), ("name", "Name", 230), ("status", "Status", 90), ("parts", "Parts", 190),
                 ("by", "Asked by", 120), ("when", "Asked", 130))


def parts_summary(eco):
    """'HCR-00001-001 Rev A' or 'HCR-00001-001 Rev A +2 more'."""
    if not eco.parts:
        return ""
    first = eco.parts[0]
    text = f"{first['pn']} Rev {first['revision']}" if first.get("revision") else first["pn"]
    return text if len(eco.parts) == 1 else f"{text} +{len(eco.parts) - 1} more"


def matches(eco, search):
    """True if `search` is in the ECO's number, name, description, a part number or who asked (any capitals)."""
    needle = " ".join((search or "").split()).lower()
    if not needle:
        return True
    texts = [eco.number, eco.name, eco.description, eco.requested_by] + [p["pn"] for p in eco.parts]
    return any(needle in text.lower() for text in texts)


def eco_table(ecos, search="", status="All", local=True):
    """Rows of (iid, values) for the ECOs window: those that match the search and the status filter."""
    rows = []
    for eco in ecos:
        if status != "All" and eco_model.STATUS_LABEL.get(eco.status) != status:
            continue
        if not matches(eco, search):
            continue
        rows.append((eco.number, (eco.number, eco.name, eco_model.STATUS_LABEL.get(eco.status, eco.status),
                                  parts_summary(eco), eco.requested_by,
                                  history_text.to_display_time(eco.requested_at, local))))
    return rows


def table_note(shown, total, problems):
    text = f"{shown} of {total} ECO{'s' if total != 1 else ''} shown."
    if problems:
        text += " Can't read: " + ", ".join(sorted(problems)) + "."
    return text


def eco_fields(eco, local=True):
    """[(label, text)] for the top of an ECO's window."""
    action = workflow_templates.label_of(eco.action) if eco.action else ""
    fields = [("Status", eco_model.STATUS_LABEL.get(eco.status, eco.status)),
              ("Workflow", f"{action} {eco.template_name}".strip()),
              ("Asked by", f"{eco.requested_by} on {history_text.to_display_time(eco.requested_at, local)}")]
    closing = next((h for h in reversed(eco.history) if h.get("event") != "opened"), None)
    if closing is not None:
        fields.append((closing.get("event", "").title(),
                       f"by {closing.get('by', '')} on {history_text.to_display_time(closing.get('at', ''), local)}"
                       + (f" - {closing['comment']}" if closing.get("comment") else "")))
    return fields


def part_rows(eco):
    """Rows of (part, revision) for an ECO's parts."""
    return [(p["pn"], p.get("revision", "")) for p in eco.parts]


def signoff_rows(eco, local=True):
    """Rows of (who, when, comment) for an ECO's sign-offs (copied in when it was closed)."""
    return [(s.get("by") or s.get("name") or s.get("id", ""), history_text.to_display_time(s.get("at", ""), local),
             s.get("comment", "")) for s in eco.signoffs]


def history_rows(eco, local=True):
    """Rows of (when, who, what) for an ECO's history."""
    return [(history_text.to_display_time(h.get("at", ""), local), h.get("by", ""),
             h.get("event", "").title() + (f": {h['comment']}" if h.get("comment") else ""))
            for h in eco.history]
