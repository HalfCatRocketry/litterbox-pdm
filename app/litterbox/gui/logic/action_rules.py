"""
action_rules.py - which buttons may act on which parts: the part kinds each action accepts, the targets
of a click (ticked parts, or the highlighted row for view-only actions), and the summary after a batch.
"""

from dataclasses import dataclass, field

from litterbox.core.doc_number import DocNumber


# The "kind" values come from litterbox_engine.PartStatus.kind
ALLOWED_KINDS = {
    "checkout": {"ok", "unclaimed"},
    "checkin": {"mine"},
    "save": {"mine"},
    "undo": {"mine"},
    "edit": {"mine"},
    "open": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},    # anything downloaded
    "open_drawing": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},
    "open_pdf": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},
    "release": {"ok", "pending"},            # on a pending part it completes an approved request (see the window)
    "make_cots": {"ok", "pending"},         # on a pending part it completes an approved request
    "revise": {"released"},
    "cancel_revision": {"ok", "mine"},
    "reopen": {"released", "cots", "pending"},
    "void": {"ok", "cots", "pending"},
    "references": {"ok", "mine", "theirs", "unclaimed", "stray", "released", "cots", "void", "missing", "pending"},
    "break_checkout": {"theirs"},           # Admin and Owner: someone else has it checked out
    "purchasing": {"ok", "mine", "unclaimed", "stray", "released", "cots", "pending"},     # not void, not theirs
    "export_files": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "pending"},
    "generate_step_pdf": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "pending"},
    "update_material": {"ok", "mine", "stray", "unclaimed", "released", "cots", "pending"},    # not someone else's
    "create_variant": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "pending"},   # not void
    "add_to_folder": {"ok", "mine", "theirs", "stray", "unclaimed", "released", "cots", "void", "missing", "pending",
                      "error"},                                  # a folder may list anything
}


# Actions that need CAD files: never for a non-CAD part (PartStatus.noncad), whatever its state
CAD_ONLY = {"open", "open_drawing", "open_pdf", "generate_step_pdf", "make_cots", "update_material"}


def usable(action, row):
    """True if the action may be used on this part (a PartStatus row) as it is now."""
    if row is None or row.kind not in ALLOWED_KINDS[action]:
        return False
    return not (action in CAD_ONLY and getattr(row, "noncad", False))


def unusable_reason(action, row):
    """Why the action can't be used on this part, for messages."""
    if row is None:
        return "not in the list"
    if action in CAD_ONLY and getattr(row, "noncad", False) and row.kind in ALLOWED_KINDS[action]:
        return "it is a non-CAD part"
    return row.state


# These can be done to several parts at once; the rest need exactly one part selected.
MULTI = {"checkout", "checkin", "save", "undo", "release", "reopen", "void", "make_cots", "export_files",
         "generate_step_pdf", "update_material", "add_to_folder"}


NAME = {            # "...cannot <name> ..."
    "checkout": "check out", "checkin": "check in", "save": "save progress on",
    "undo": "undo the checkout of", "edit": "edit the details of", "open": "open", "open_drawing": "open the drawing of", "open_pdf": "open the PDF of", "release": "release", "make_cots": "make COTS", "revise": "revise", "cancel_revision": "cancel the revision of", "reopen": "unrelease", "void": "void", "references": "show the references of",
    "break_checkout": "break the checkout of", "purchasing": "change the purchasing info of",
    "export_files": "export the files of", "generate_step_pdf": "make the STEP/PDF of",
    "update_material": "update the material of", "create_variant": "make a variant of",
    "add_to_folder": "put in a folder",
}


PAST = {            # "<past> 2 parts"
    "checkout": "Checked out", "checkin": "Checked in", "save": "Saved progress on",
    "undo": "Undid checkout of", "edit": "Edited", "open": "Opened", "open_drawing": "Opened the drawing of", "open_pdf": "Opened the PDF of", "release": "Released", "make_cots": "Made COTS", "revise": "Revised", "cancel_revision": "Cancelled the revision of", "reopen": "Unreleased", "void": "Voided", "references": "Showed the references of",
    "break_checkout": "Broke the checkout of", "purchasing": "Changed the purchasing info of",
    "export_files": "Exported the files of", "generate_step_pdf": "Made the STEP/PDF of",
    "update_material": "Updated the material of", "create_variant": "Made a variant of",
    "add_to_folder": "Put in a folder",
}


@dataclass
class ActionPlan:
    targets: list = field(default_factory=list)     # part numbers the action will run on
    skipped: list = field(default_factory=list)     # [(pn, reason)] that were selected but can't be used
    message: str = ""                               # if not empty: show this and do nothing


def plan_action(action, selected, rows_by_pn, pending=None):
    """Decide which of the selected parts an action applies to.

    `selected` is a list of PN objects; `rows_by_pn` maps PN -> PartStatus. `pending` maps a part (as text) to the
    job that is queued or running for it: a part with a job in progress can't have anything else done to it yet
    (except looking at it).
    """
    noun = "document" if are_documents(selected) else "part"
    if not selected:
        return ActionPlan(message="Select a part first (use its box on the left)." if action not in VIEW_ONLY else "Click a part first.")
    if action not in MULTI and len(selected) > 1:
        return ActionPlan(message=f"Select just one {noun} to {NAME[action]}.")

    targets, skipped = [], []
    for pn in selected:
        row = rows_by_pn.get(pn)
        if pending and action not in LOOKS and str(pn) in pending:
            skipped.append((pn, f"busy: {pending[str(pn)].lower()}"))
        elif usable(action, row):
            targets.append(pn)
        else:
            skipped.append((pn, unusable_reason(action, row)))

    plan = ActionPlan(targets, skipped)
    if not targets:
        if len(skipped) == 1:
            pn, reason = skipped[0]
            plan.message = f"Can't {NAME[action]} {pn}: {reason}."
        else:
            plan.message = f"None of the selected {noun}s can be used to {NAME[action]}."
    return plan


VIEW_ONLY = {"open", "open_drawing", "open_pdf", "references",      # these only look at a part, so the blue highlighted row will do
             "create_variant"}                                   # (Create Variant copies a part, leaving it as it is)

EXPORTS = {"export_files"}      # copies out of the vault: the ticked parts, or else the highlighted one; never busy

# The ticked parts, or else the highlighted one: its window lists the parts before anything is done
TICKED_OR_HIGHLIGHTED = EXPORTS | {"generate_step_pdf", "update_material", "add_to_folder"}

LOOKS = VIEW_ONLY | EXPORTS | {"add_to_folder"}     # change nothing in the vault's parts, so a part with a job
                                                    # running can still be used


def choose_targets(action, ticked, highlighted):
    """Which parts an action applies to. Looking at a part (VIEW_ONLY) uses the highlighted row, or the one
    selected part if nothing is highlighted. Everything else, which changes or proposes a change, uses only the
    parts whose boxes are selected, so a stray click on a row can never be what Release or Check Out acts on."""
    if action in TICKED_OR_HIGHLIGHTED:
        return list(ticked) or list(highlighted)
    if action in VIEW_ONLY:
        if highlighted:
            return list(highlighted)
        return list(ticked) if len(ticked) == 1 else []
    return list(ticked)


# The main window's buttons that depend on the selection. Button text -> action key.
BUTTON_ACTIONS = {
    "Check Out": "checkout", "Check In": "checkin", "Save Progress": "save", "Undo Checkout": "undo",
    "Open": "open", "Open Drawing": "open_drawing", "Open PDF": "open_pdf", "Edit Details": "edit",
    "References...": "references",
    "Release": "release", "Revise": "revise", "Cancel Revision": "cancel_revision", "Make COTS": "make_cots",
    "Unrelease": "reopen", "Void": "void", "Details": "history", "Break Checkout": "break_checkout",
    "Purchasing Info": "purchasing", "Export Files": "export_files", "Generate STEP/PDF": "generate_step_pdf",
    "Update Material": "update_material", "Create Variant": "create_variant", "Add to Folder": "add_to_folder",
}


def action_available(action, ticked, highlighted, rows_by_pn, pending=None):
    """True if every part the action would act on is one it can be used on (so its button may light up)."""
    targets = choose_targets("open" if action == "history" else action, ticked, highlighted)
    if not targets:
        return False
    if pending and action not in LOOKS and action != "history" and any(str(pn) in pending for pn in targets):
        return False
    if action == "history":
        return len(targets) == 1
    if action not in MULTI and len(targets) > 1:
        return False
    return all(usable(action, rows_by_pn.get(pn)) for pn in targets)


def why_not(action, ticked, highlighted, rows_by_pn, pending=None):
    """Why an action's button is greyed out, for its tooltip ("" if it can be used)."""
    if action_available(action, ticked, highlighted, rows_by_pn, pending):
        return ""
    looking = action in LOOKS or action == "history"
    targets = choose_targets("open" if action == "history" else action, ticked, highlighted)
    if not targets:
        return "Click a part first." if looking else "Tick a part's box first."
    name = NAME.get(action, "see the details of")
    if (action == "history" or action not in MULTI) and len(targets) > 1:
        return f"Tick just one part to {name}."
    if pending and not looking:
        for pn in targets:
            if str(pn) in pending:
                return f"{pn.short} is busy: {pending[str(pn)].lower()}."
    for pn in targets:
        row = rows_by_pn.get(pn)
        if row is None:
            return f"{pn.short} is not in the list."
        if not usable(action, row):
            return f"Can't {name} {pn.short}: {unusable_reason(action, row)}."
    return ""


def button_states(ticked, highlighted, rows_by_pn, pending=None):
    """{button text: True if it should be usable} for the main window's selection-dependent buttons."""
    return {text: action_available(action, ticked, highlighted, rows_by_pn, pending)
            for text, action in BUTTON_ACTIONS.items()}


def are_documents(numbers):
    """True when every number is a document's (PROP-0001), so messages say "document" rather than "part"."""
    numbers = list(numbers)
    return bool(numbers) and all(isinstance(number, DocNumber) for number in numbers)


def parts_text(count, documents=False):
    """'1 part', '3 parts' (or '3 documents')."""
    return f"{count} {'document' if documents else 'part'}" + ("" if count == 1 else "s")


def summary(action, done, failed=0, skipped=0, documents=False):
    """One line saying what just happened, e.g. 'Checked out 2 parts, 1 failed' (or '2 documents')."""
    if done:
        text = f"{PAST[action]} {parts_text(done, documents)}"
        if failed:
            text += f", {failed} failed"
    else:
        text = f"Could not {NAME[action]} {parts_text(failed or skipped or 1, documents)}"
    if skipped and done:
        text += f", skipped {skipped}"
    return text
