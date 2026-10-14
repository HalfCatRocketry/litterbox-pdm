"""
errors.py - the exceptions every part of Litterbox uses.

Every error Litterbox raises on purpose is a LitterboxError (or a subclass), and its message is safe to show to a
user. Callers need only one 'except'.
"""

from pathlib import Path


class LitterboxError(Exception):
    """Raised when something goes wrong. The message is safe to show to a user."""


class NothingToSaveError(LitterboxError):
    """A save found nothing different from what the vault already has, so there was nothing to commit. This is not
    a failure: the window shows it as information."""


class NoChangesError(LitterboxError):
    """A check-in found nothing to upload. Nothing was changed: the part is still checked out.

    `files` lists the CAD files that have no changes. To check in anyway, call
    checkin(..., allow_unchanged=True).
    """

    def __init__(self, pn, files):
        self.pn = pn
        self.files = list(files)
        names = ", ".join(Path(f).name for f in self.files)
        super().__init__(
            f"No changes were detected in {pn}" + (f" ({names})" if names else "") + ".\n"
            "It is still checked out to you. Use Undo Checkout to release it, or check in anyway."
        )
