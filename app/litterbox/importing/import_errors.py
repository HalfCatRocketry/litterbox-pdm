"""
import_errors.py - what can go wrong in an import, as exceptions the window can explain.
"""

from litterbox.errors import LitterboxError


class ImportFailed(LitterboxError):
    """The import could not be done. The message is safe to show to a user. Nothing was left behind."""


class FamilyFull(ImportFailed):
    """More parts are being imported to one base number than it has unused variant numbers."""


class ExternalReferences(ImportFailed):
    """Some files reference files that are not part of the import. `references` is [(file, referenced file)].

    The caller may ask the user and, if they agree, try again with allow_external.
    """

    def __init__(self, message, references):
        super().__init__(message)
        self.references = list(references)


class ImportCancelled(ImportFailed):
    """The user cancelled. Everything copied so far has been removed."""


class PNConflict(ImportFailed):
    """Typed-in part numbers are taken. Nothing was changed; the user should fix the highlighted rows."""

    def __init__(self, message, conflicts, renumbered=()):
        super().__init__(message)
        self.conflicts = list(conflicts)
        self.renumbered = list(renumbered)
