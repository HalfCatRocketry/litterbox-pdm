"""
sw_errors.py - what can go wrong talking to SolidWorks (not open, not installed, refused to copy a file), as an
error whose message is safe to show to a user.
"""

from litterbox.errors import LitterboxError


class SolidWorksError(LitterboxError):
    """SolidWorks could not do what Litterbox asked. The message says what to do next."""
