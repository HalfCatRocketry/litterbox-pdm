"""
change_text.py - the parts table of the Workflow, Review and Release/Void windows: its columns (Part, Name, Rev,
Form, Fit, Function, Dispo), what each cell shows, which parts take form, fit, function and a disposition, and the
check that every disposition asked for was chosen. The rules are records/record_changes.py's.
"""

from litterbox.records import record_changes
from litterbox.workflows import workflow_templates


COLUMNS = (("pn", "Part"), ("name", "Name"), ("rev", "Rev"), ("form", "Form"), ("fit", "Fit"),
           ("function", "Function"), ("dispo", "Dispo"))
WIDTHS = {"rev": 64, "form": 54, "fit": 46, "function": 72, "dispo": 150}     # the least; each also fits its text
ALWAYS = ("pn", "name", "rev")      # shown even when Form, Fit, Function and Dispo aren't asked

TICKED, UNTICKED, NOT_ASKED = "☑", "☐", "—"
CHOOSE = "Choose..."


def rev_text(revision, earlier):
    """'A → B' when a release replaces an earlier revision, else 'B'."""
    return f"{earlier} → {revision}" if earlier else revision


def asks(pn, action, revision, released_revision):
    """(form/fit/function asked, disposition asked) for a part going through `action` (any workflow action)."""
    return record_changes.wanted(pn, workflow_templates.base_action(action), revision, released_revision)


def cells(pn, name, revision, earlier, change, asked):
    """The values of one row, in COLUMNS order. `change` is {"changed", "disposition"}, `asked` is asks()."""
    changed = (change or {}).get("changed") or []
    boxes = [(TICKED if key in changed else UNTICKED) if asked[0] else NOT_ASKED for key in record_changes.CHANGES]
    disposition = (change or {}).get("disposition")
    dispo = (record_changes.DISPOSITION_LABEL.get(disposition, CHOOSE) if asked[1] else NOT_ASKED)
    return [str(pn), name, rev_text(revision, earlier)] + boxes + [dispo]


def toggled(change, key):
    """The change with form, fit or function (`key`) ticked or unticked."""
    change = dict(change or {})
    changed = set(change.get("changed") or [])
    changed ^= {key}
    change["changed"] = [c for c in record_changes.CHANGES if c in changed]
    return change


def with_disposition(change, disposition):
    return dict(change or {}, disposition=disposition)


def missing_dispositions(parts, action, changes):
    """The part numbers (text) that are asked for a disposition and haven't one. `parts` is [(PN, revision,
    released revision)]."""
    return [str(pn) for pn, rev, released in parts
            if asks(pn, action, rev, released)[1] and not (changes.get(str(pn)) or {}).get("disposition")]


def missing_text(missing):
    """The message for parts without a disposition."""
    if len(missing) == 1:
        return f"Choose a Dispo for {missing[0]}: what to do with the parts already made."
    return f"Choose a Dispo for {', '.join(missing)}: what to do with the parts already made."


def kept(parts, action, changes):
    """{part number text: change} for the parts that take one, with only what each is asked for."""
    result = {}
    for pn, rev, released in parts:
        asked = asks(pn, action, rev, released)
        if any(asked):
            change = record_changes.clean(changes.get(str(pn)) or {}, asked[0], False)
            if asked[1]:
                change["disposition"] = (changes.get(str(pn)) or {}).get("disposition")
            result[str(pn)] = change
    return result


def disposition_choices():
    """[(label, key)] for the Dispo menu."""
    return [(record_changes.DISPOSITION_LABEL[key], key) for key in record_changes.DISPOSITIONS]
