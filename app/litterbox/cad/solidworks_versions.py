"""
solidworks_versions.py - which SolidWorks may work in a vault: the version the org has chosen (the vault setting
solidworks_version, see vault/config.py) against the one installed on this computer.

A file saved in a newer SolidWorks can't be opened in an older one, and SolidWorks moves a file up to its own
version whenever it saves it. So someone whose SolidWorks is newer than the org's is stopped before Check Out
(and the other actions that save SolidWorks files); someone whose SolidWorks is older is only warned.
Versions are years, as people know them (2024); SolidWorks itself counts majors (32 for 2024).
"""

from litterbox.cad.solidworks import sw_process

FIRST_YEAR, LAST_YEAR = 2010, 2100      # the years a vault setting may hold
CHOICES_FROM = 2018                     # the oldest year the Vault Settings window offers

OK, NEWER, OLDER = "ok", "newer", "older"


def year_of_major(major):
    """SolidWorks' major version as the year it is sold as: 32 -> 2024. None stays None."""
    return None if major is None else major + 1992


def installed_year():
    """The year of the SolidWorks installed on this computer, or None if there isn't one."""
    return year_of_major(sw_process.installed_major_version())


def compare(org_year, installed):
    """OK when the org has no version set or this computer has no SolidWorks; NEWER or OLDER otherwise."""
    if not org_year or not installed or installed == org_year:
        return OK
    return NEWER if installed > org_year else OLDER


def blocked_text(org_year, installed, action):
    """Why an action is refused on a computer whose SolidWorks is newer than the org's. `action` is like
    'check out HCR-00042-001'."""
    return (f"Litterbox won't {action}: your SolidWorks is {installed}, but this org works in SolidWorks "
            f"{org_year}. Files saved in {installed} can't be opened in {org_year}, so nobody else could open them.\n\n"
            f"Use SolidWorks {org_year} on this computer, or ask an Admin to change the org's SolidWorks version "
            "(Team > Vault Settings).")


def older_text(org_year, installed):
    """The warning for a computer whose SolidWorks is older than the org's."""
    return (f"Your SolidWorks is {installed}, older than this org's SolidWorks {org_year}. Files saved in "
            f"{org_year} won't open in your SolidWorks.")


def year_choices(this_year, chosen=None):
    """The years the Vault Settings window offers, newest first: up to next year (SolidWorks sells next year's
    version in the autumn), down to CHOICES_FROM, plus the vault's own if it is outside that."""
    years = list(range(this_year + 1, CHOICES_FROM - 1, -1))
    if chosen and chosen not in years:
        years.append(chosen)
        years.sort(reverse=True)
    return years
