"""
git_identity_text.py - the words of the window that asks for the name and email git puts on your commits
(gui/dialogs/git_identity_dialog.py, git/git_identity.py).
"""

TITLE = "Your name for this vault"
NOT_NOW = ("Git doesn't know your name or email yet, so nothing you change can be uploaded. Litterbox asks again "
           "the next time it starts.")


def intro(wanted, vault_name=""):
    """What the window says above the boxes, for a git_identity.Wanted."""
    where = f"the {vault_name} vault" if vault_name else "this vault"
    if wanted.missing:
        what = " and ".join({"name": "name", "email": "email address"}[m] for m in wanted.missing)
        return (f"Git doesn't know your {what} yet, so it can't save your changes in {where}. Enter them here: "
                "they go on every change you upload, and are set for this vault only.")
    return (f"Git puts a different name on your changes in {where} than the team list has for you. Use the team "
            "list's? (Set for this vault only; you can change it here.)")


def cancel_text(wanted):
    """The button that closes the window without saving."""
    return "Not now" if wanted.missing else "Keep as it is"
