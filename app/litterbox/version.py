"""
version.py - which version of Litterbox this is, and which vault layout it understands.

Two separate numbers:

    VERSION       the program's own version, "MAJOR.MINOR.PATCH". Change it for every release. The installer,
                  the update check and the window title all read it from here (nowhere else).
    VAULT_FORMAT  the layout of the files inside a vault (part records, .litterbox files). Raise it ONLY when a
                  change would make an older Litterbox misread a vault. Most releases never touch it.

A vault records what it needs in .litterbox/config.yaml:

    format_version: 1               the vault's layout. A Litterbox that only understands older layouts refuses it.
    min_litterbox_version: 0.1.0    the oldest Litterbox allowed to work in this vault.

Missing values mean format 1 and no minimum, so vaults made before these existed keep working.
"""

import sys

VERSION = "0.5.2"
VAULT_FORMAT = 1


def parse(text):
    """'0.1.0' (or 'v0.1.0') -> (0, 1, 0). Raises ValueError if it isn't MAJOR.MINOR.PATCH."""
    parts = str(text).strip().lstrip("vV").split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"'{text}' is not a version like 1.2.3")
    return tuple(int(p) for p in parts)


def is_newer(candidate, than=None):
    """Is `candidate` a later version than `than` (default: this program)?"""
    return parse(candidate) > parse(VERSION if than is None else than)


def is_installed_build():
    """True in the installed program, False when running from the source files (a development copy)."""
    return bool(getattr(sys, "frozen", False))


def display():
    """The version for people to read: '0.1.0', or '0.1.0 (from source)' for a development copy."""
    return VERSION if is_installed_build() else f"{VERSION} (from source)"
