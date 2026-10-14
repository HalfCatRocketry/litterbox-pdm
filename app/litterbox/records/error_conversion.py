"""
error_conversion.py - turning record and part-number errors into LitterboxError.

Decorate a public function with @converts_errors so it raises only LitterboxError, whatever went wrong in the
records or part-number rules underneath.
"""

from functools import wraps

from litterbox.core.pn import PNError
from litterbox.errors import LitterboxError
from litterbox.records import registry


def converts_errors(func):
    """Make every public function raise only LitterboxError, so callers need one 'except'."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (registry.RegistryError, PNError) as e:
            raise LitterboxError(str(e)) from e
    return wrapper
