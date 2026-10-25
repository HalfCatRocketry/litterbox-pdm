"""
update_text.py - what the update check says (gui/main_window/update_checks.py; the check itself is user/updater.py).
"""

BETA_QUESTION = ("Betas are the next version before it is finished, for trying new things early. They may have more "
                 "bugs; please report any with Help > Report a problem.\n\n"
                 "Try them in a test vault, or have the whole team move to the beta together: a beta can make a "
                 "vault need the version it leads to, which teammates on the released version don't have yet.\n\n"
                 "Get beta versions?")
BETA_ON = ("Litterbox will offer betas as well as releases. Once the version a beta leads to is released, you are "
           "offered that, as everyone is.")
BETA_OFF = ("Litterbox will offer releases only. If you have a beta now, you keep it until a newer release comes out: "
            "Litterbox never goes back to an older version.")
REVOKED = ("Update check: the Litterbox maintainers have withdrawn an update key. It won't be trusted on this "
           "computer again.")


def newest(current):
    return f"You have the newest version ({current})."


def moved(repo):
    return f"Litterbox's releases have moved to github.com/{repo}. Updates now come from there."


def offer(new, current, notes="", beta=False):
    """The question before updating."""
    which = f"Litterbox {new} (a beta)" if beta else f"Litterbox {new}"
    notes = f"\n\n{notes}" if notes else ""
    return (f"{which} is available. You have {current}.{notes}\n\nUpdate now? Litterbox will close, update and start "
            "again. Your settings and vault are not touched.")
