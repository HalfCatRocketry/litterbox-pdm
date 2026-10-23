"""
cad_errors.py - what can go wrong talking to a CAD program (not open, not installed, refused to copy a file), as an
error whose message is safe to show to a user. Each program's own error is a kind of CadError
(cad/solidworks/sw_errors.py), so the rest of Litterbox catches CadError whatever the program.
"""

from litterbox.errors import LitterboxError


class CadError(LitterboxError):
    """A CAD program could not do what Litterbox asked. The message says what to do next."""
