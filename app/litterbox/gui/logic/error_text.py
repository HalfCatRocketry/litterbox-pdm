"""
error_text.py - turning an error into plain-language advice for the banner and the Details window.
"""

import time


def shorten(text, limit=1200):
    """Keep very long error text from filling the screen."""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... (the full text is in the log)"


def error_advice(message):
    """A plain next step for an error message, from what it says. Always returns something."""
    text = str(message).lower()
    if "could not unlock" in text or "could not be unlocked" in text:
        return ("Your changes are saved. Press Check In on the same parts again to finish releasing their locks.")
    if any(k in text for k in ("could not resolve host", "unable to access", "timed out", "connection refused",
                               "network is unreachable", "could not read from remote", "early eof", "ssl")):
        return "Check your internet connection (and VPN, if you use one), then press Refresh. Nothing was lost."
    if any(k in text for k in ("authentication failed", "permission denied", "401", "403", "could not read username",
                               "access denied", "login")):
        return ("Git rejected your sign-in. Sign in to the host again (for example by running a git command in a "
                "terminal), then try again.")
    if "already checked out by" in text or "locked by" in text:
        return "Someone else has it. Ask them to check it in, or ask an Admin to release their lock."
    if "push was rejected" in text or "non-fast-forward" in text or "failed to push" in text:
        return "Press Get Latest and try again. If it keeps happening, ask an Admin: the vault may be locked down."
    if "not allowed" in text or "you can't" in text or "role" in text and "need" in text:
        return "You don't have the role for that. Ask an Admin if you should."
    if "unexpected error" in text:
        return ("Something Litterbox did not expect. Press Refresh. If it happens again, press Report... below "
                "(or Help > Report a problem...) to send a problem report.")
    return "Press Refresh to see where things stand, then try again. The log below has the details."


def error_report_text(notes):
    """The text of the error Details window: each problem, what it was doing, and what to do about it."""
    blocks = []
    for note in notes:
        when = time.strftime("%H:%M:%S", time.localtime(note.when))
        blocks.append(f"[{when}] {note.label}\n\n{shorten(note.message)}\n\nWhat to do: {note.advice}")
    return "\n\n----------------------------------------\n\n".join(blocks)
