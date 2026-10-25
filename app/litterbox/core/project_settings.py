"""
project_settings.py - the org's rules for making projects (core/projects.py), set by an Admin in Team > Vault
Settings...:

    project_creators: anyone        # who may add a project: Admins and the Owner (the default), or anyone on the team
    project_min_digits: 3           # the fewest starting digits a project may have (none by default)

A short prefix sets aside a big block of part numbers (with 6 digits, '1' is 100000 parts), so the minimum stops one
project taking too many. Anyone else is refused a shorter one; an Admin or the Owner is warned and may go ahead.
Projects that already have a shorter prefix keep it. Either setting makes the vault need MIN_LITTERBOX: an older
Litterbox would let anyone past them.
"""

from litterbox.core import part_number
from litterbox.core.projects import ProjectError

ADMINS, ANYONE = "admins", "anyone"
CREATORS = (ADMINS, ANYONE)
CREATOR_LABELS = {ADMINS: "Admins and the Owner", ANYONE: "Anyone on the team"}
MIN_LITTERBOX = "0.6.4"         # the first Litterbox that keeps to these settings


def check_creators(value):
    """Who may add a project: ADMINS (also for no value) or ANYONE. Raises ProjectError."""
    if value in (None, ""):
        return ADMINS
    if value not in CREATORS:
        raise ProjectError(f"project_creators must be one of {', '.join(CREATORS)}.")
    return value


def check_min_digits(value, digits=None):
    """The fewest starting digits a project may have: 0 for no minimum (also for no value), else 1 to one less than
    the part number's digits. Raises ProjectError."""
    digits = digits or part_number.BASE_DIGITS
    if value in (None, "", 0):
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value < digits:
        raise ProjectError(f"The fewest starting digits for a project must be a number from 1 to {digits - 1} "
                           "(or none).")
    return value


def too_short(prefix, minimum):
    """True if these starting digits are fewer than the minimum (0: no minimum)."""
    return bool(minimum) and len(str(prefix or "").strip()) < minimum


def short_text(prefix, minimum, digits=None):
    """Why these starting digits are too few, in words."""
    digits = digits or part_number.BASE_DIGITS
    size = 10 ** (digits - len(str(prefix).strip()))
    return (f"A project needs at least {minimum} starting digits (the org's setting): {prefix} would set aside "
            f"{size:,} part numbers.")
