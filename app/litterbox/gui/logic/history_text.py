"""
history_text.py - the History window and revision lists: event labels, local times, and which revisions
of a part can be opened.
"""

from datetime import datetime, timezone
from pathlib import PurePosixPath

from litterbox.core import revision_letters
from litterbox.gui.logic import list_view
from litterbox.records import record_revisions
from litterbox.workflows import workflow_templates


EVENT_LABELS = {
    "created": "Created", "checked_out": "Checked out", "checked_in": "Checked in",
    "released": "Released", "reopened": "Unreleased", "voided": "Voided", "made_cots": "Made COTS",
    "edited": "Edited details", "revised": "Revised", "revision_cancelled": "Revision cancelled",
    "references_updated": "Parts used updated",
    "release_requested": "Requested", "release_signed": "Signed off", "release_rejected": "Request rejected",
    "release_withdrawn": "Request withdrawn", "workflow_reassigned": "Signer changed",
}


REQUEST_EVENTS = {"release_requested", "release_rejected"}          # shown as "<Action> requested" / "rejected"


def to_display_time(text, local=True):
    """'2026-10-05T14:02:41Z' -> '2026-10-05 14:02' (in your time zone if local=True)."""
    try:
        moment = datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return str(text)
    if local:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def format_history(record, local=True):
    """Rows of (when, who, what, details) for a record, newest first."""
    rows = []
    for event in reversed(record.history):
        parts = []
        if event.get("eco"):
            parts.append(str(event["eco"]))
        if event.get("reason"):
            parts.append(str(event["reason"]))
        if event.get("comment"):
            parts.append(str(event["comment"]))
        if event.get("event") == "revised" and event.get("from_revision"):
            parts.append(f"Rev {event['from_revision']} to Rev {event.get('revision', '')}")
        if event.get("event") == "revision_cancelled" and event.get("cancelled"):
            parts.append(f"Rev {event['cancelled']}")
        used = event.get("references")
        if used is not None and event.get("event") == "checked_in":
            parts.append("uses " + (", ".join(used) if used else "no parts"))
        elif isinstance(used, dict):
            parts.append("; ".join(f"Rev {rev} uses " + (", ".join(stems) if stems else "no parts")
                                   for rev, stems in used.items()))
        changes = event.get("changes") or []
        if changes:
            parts.append("; ".join(str(c) for c in changes))
        if event.get("event") == "release_signed" and event.get("roles"):
            parts.append("as " + ", ".join(event["roles"]))
        if event.get("event") == "release_requested" and event.get("waiting_on"):
            parts.append("needs " + ", ".join(event["waiting_on"]))
        if event.get("event") == "release_rejected" and event.get("signed"):
            parts.append("had been signed by " + ", ".join(event["signed"]))
        if event.get("event") == "released" and event.get("signoffs"):
            parts.append("signed off by " + ", ".join(event["signoffs"]))
        files = event.get("files") or []
        if files:
            parts.append(", ".join(PurePosixPath(f).name for f in files))
        name = event.get("event", "")
        label = EVENT_LABELS.get(name, str(name))
        if name in REQUEST_EVENTS:
            label = workflow_templates.label_of(event.get("action") or "release") + (" requested" if name == "release_requested"
                                                                         else " rejected")
        if name == "released" and event.get("override"):
            label = "Released (Admin override)"
        rows.append((
            to_display_time(event.get("at", ""), local),
            str(event.get("by", "")),
            label,
            "  -  ".join(parts),
        ))
    return rows


def row_revisions(row):
    """{revision: [files]} for a part row (older test rows only have .files for the working revision)."""
    revisions = getattr(row, "revisions", None)
    if revisions:
        return revisions
    return {getattr(row, "revision", "A"): list(row.files)} if row.files else {}


def revision_label(row, rev):
    """'Rev B (working)' / 'Rev A (released)' for the question asked before opening."""
    released = getattr(row, "released_revision", "")
    if rev == released and not (rev == getattr(row, "revision", "") and row.record_status != "released"):
        return f"Rev {rev} (released)"
    return f"Rev {rev} (working)"


def revision_rows(record, revisions):
    """Rows of (revision, state, details) for the History window's revision list, newest first.

    `revisions` is {revision: [files]}. A revision appears if it has files, is the working
    revision, or was released at some point.
    """
    released = {}
    for event in record.history:
        if event.get("event") == "released" and event.get("revision"):
            released[event["revision"]] = event
    cancelled = set(record_revisions.cancelled_revisions(record))
    letters = set(revisions) | set(released) | {record.revision} | cancelled
    rows = []
    for rev in sorted(letters, key=revision_letters.revision_number, reverse=True):
        event = released.get(rev)
        if rev in cancelled:
            rows.append((rev, "Cancelled", "kept in the cancelled-revs folder"))
            continue
        if rev == record.revision and record.status != "released":
            state = "In work" if record.status == "in_work" else record.status.replace("_", " ").title()
        elif event:
            state = "Released" if rev == record.released_revision else "Released (superseded)"
        else:
            state = "No release"
        details = []
        if event:
            details.append(f"by {event.get('by', '')} on {to_display_time(event.get('at', ''))}")
        types = list_view.file_types(revisions.get(rev, []))
        details.append(types if types else "no files")
        rows.append((rev, state, "   ".join(details)))
    return rows
