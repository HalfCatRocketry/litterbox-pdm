"""
job_text.py - what the status banner says while a job runs ("Checking in 3 parts...").
"""

from litterbox.gui.logic import action_rules


PROGRESS = {        # what the banner says while a job runs: "<progress> 3 parts"
    "checkout": "Checking out", "checkin": "Checking in", "save": "Saving progress on", "undo": "Undoing checkout of",
    "edit": "Editing", "release": "Releasing", "make_cots": "Making COTS", "revise": "Revising",
    "cancel_revision": "Cancelling the revision of", "reopen": "Unreleasing", "void": "Voiding",
}


def job_label(action, count):
    """'Checking in 3 parts' (or 'Checking in HCR-00007-001' is left to the caller for one part's name)."""
    return f"{PROGRESS.get(action, 'Working on')} {action_rules.parts_text(count)}"


def busy_state_text(state, label):
    """What the Status column shows for a part that has a job queued or running."""
    return f"\u23f3 {label.lower()}..."
