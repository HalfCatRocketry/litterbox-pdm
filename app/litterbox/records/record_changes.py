"""
record_changes.py - what a new revision changed (form, fit and/or function), and what to do with the parts already
made to an earlier revision (its disposition: use as is, rework, scrap, return to supplier). Both are kept in the
part's history.

    release of Rev B or later   the release event lists what changed (`changed: [form, fit]`), and a `disposition`
                                event on the revision released before it says what to do with its parts
    void                        a `disposition` event on the voided revision
    first release (Rev A)       neither: nothing earlier was changed, and no parts of an earlier revision exist

Documents take neither. A workflow carries them in each part's request (`pending["change"]`) until it completes.
"""

from litterbox.core.doc_number import DocNumber
from litterbox.core.revision_letters import FIRST_REVISION
from litterbox.errors import LitterboxError
from litterbox.records import record_lifecycle


FORM, FIT, FUNCTION = "form", "fit", "function"
CHANGES = (FORM, FIT, FUNCTION)
CHANGE_LABEL = {FORM: "Form", FIT: "Fit", FUNCTION: "Function"}

USE_AS_IS, REWORK, SCRAP, RETURN = "use_as_is", "rework", "scrap", "return_to_supplier"
DISPOSITIONS = (USE_AS_IS, REWORK, SCRAP, RETURN)
DISPOSITION_LABEL = {USE_AS_IS: "Use As Is", REWORK: "Rework", SCRAP: "Scrap", RETURN: "Return To Supplier"}

EVENT_DISPOSITION = "disposition"

RELEASE, VOID = "release", "void"        # the part actions that take them (workflow_templates' names)


class ChangeError(LitterboxError):
    """Form, fit, function or a disposition is missing or wrong. The message is safe to show."""


def earlier_revision(revision, released_revision):
    """The revision released before `revision` ("" for none): whose parts a release of `revision` disposes of."""
    return released_revision if released_revision and released_revision != revision else ""


def wanted(pn, action, revision, released_revision):
    """(asks what changed, asks for a disposition) for a part (or document) going through `action` (a part
    action, workflow_templates.base_action) at `revision`, the latest released one being `released_revision`."""
    if isinstance(pn, DocNumber):
        return False, False
    if action == RELEASE and revision != FIRST_REVISION:
        return True, bool(earlier_revision(revision, released_revision))
    if action == VOID:
        return False, True
    return False, False


def first_release(revision):
    """True for a release at Rev A, which changes nothing and so needs no ECO."""
    return revision == FIRST_REVISION


def clean(info, asks_changes, asks_disposition, where=""):
    """{"changed": [...], "disposition": key} checked, keeping only what is asked for ({} when nothing is). A
    disposition is required when asked for. Raises ChangeError."""
    info = info or {}
    result = {}
    if asks_changes:
        changed = info.get("changed") or []
        if not isinstance(changed, (list, tuple)) or any(c not in CHANGES for c in changed):
            raise ChangeError(f"{where}What changed must be form, fit and/or function.")
        result["changed"] = [c for c in CHANGES if c in changed]
    if asks_disposition:
        disposition = info.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ChangeError(f"{where}Choose a disposition (Dispo) for the parts already made.")
        result["disposition"] = disposition
    return result


def changes_text(changed):
    """['form', 'fit'] -> 'Form, Fit'; [] -> 'None'."""
    return ", ".join(CHANGE_LABEL[c] for c in CHANGES if c in (changed or [])) or "None"


def record_disposition(record, by, disposition, revision, because):
    """Add a disposition event for `revision`'s parts (`because`: 'Rev B released', 'voided'). Returns it."""
    return record_lifecycle.add_event(record, EVENT_DISPOSITION, by, revision=revision, disposition=disposition,
                                      reason=because)


def disposition_of(record, revision):
    """The disposition key last given for a revision's parts, or ""."""
    found = [e for e in record.history if e.get("event") == EVENT_DISPOSITION and e.get("revision") == revision]
    return found[-1].get("disposition", "") if found else ""


def disposition_event(record, revision):
    """The last disposition event of a revision, or None."""
    found = [e for e in record.history if e.get("event") == EVENT_DISPOSITION and e.get("revision") == revision]
    return found[-1] if found else None


def changed_in(record, revision):
    """What the release of `revision` said changed (['form', ...]), or None if it didn't say."""
    found = [e for e in record.history if e.get("event") == "released" and e.get("revision") == revision]
    return found[-1].get("changed") if found and "changed" in found[-1] else None
