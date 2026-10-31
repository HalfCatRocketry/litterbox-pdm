"""
version.py - which version of Litterbox this is, and which vault layout it understands.

Two separate numbers:

    VERSION       the program's own version, "MAJOR.MINOR.PATCH", or "MAJOR.MINOR.PATCH-beta.N" for a beta (see
                  docs/RELEASING.md). Change it for every release. The installer, the update check and the window
                  title all read it from here (nowhere else).
    VAULT_FORMAT  the layout of the files inside a vault (part records, .litterbox files). Raise it ONLY when a
                  change would make an older Litterbox misread a vault. Most releases never touch it.

A vault records what it needs in .litterbox/config.yaml:

    format_version: 1               the vault's layout. A Litterbox that only understands older layouts refuses it.
    min_litterbox_version: 0.1.0    the oldest Litterbox allowed to work in this vault.

Missing values mean format 1 and no minimum, so vaults made before these existed keep working. A beta counts as
the version it leads to there: 0.7.0-beta.2 may open a vault that needs 0.7.0.
"""

import re
import sys

VERSION = "1.0.4"
VAULT_FORMAT = 1

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.([1-9]\d*))?$")


def _match(text):
    found = _VERSION.match(str(text).strip().lstrip("vV"))
    if not found:
        raise ValueError(f"'{text}' is not a version like 1.2.3 (or 1.2.3-beta.1)")
    return found


def parse(text):
    """'0.1.0' (or 'v0.1.0') -> (0, 1, 0). A beta gives the version it leads to: '0.7.0-beta.2' -> (0, 7, 0).
    Raises ValueError if it isn't MAJOR.MINOR.PATCH, with or without -beta.N."""
    return tuple(int(p) for p in _match(text).groups()[:3])


def release(text=None):
    """The version a beta leads to, as text ('0.7.0-beta.2' -> '0.7.0'; default: this program). What a vault is
    given as its minimum, since a Litterbox before 0.6.5 can't read a beta's version."""
    return ".".join(str(p) for p in parse(VERSION if text is None else text))


def is_beta(text):
    """Is this a beta's version ('0.7.0-beta.2')? Raises ValueError like parse."""
    return _match(text).group(4) is not None


def order(text):
    """A key that sorts versions oldest first, each beta before the version it leads to:
    0.6.5 < 0.7.0-beta.1 < 0.7.0-beta.2 < 0.7.0."""
    beta = _match(text).group(4)
    return parse(text) + ((0, int(beta)) if beta else (1, 0))


def is_newer(candidate, than=None):
    """Is `candidate` a later version than `than` (default: this program)? Betas count as older than their version."""
    return order(candidate) > order(VERSION if than is None else than)


def is_installed_build():
    """True in the installed program, False when running from the source files (a development copy)."""
    return bool(getattr(sys, "frozen", False))


def display():
    """The version for people to read: '0.1.0', or '0.1.0 (from source)' for a development copy."""
    return VERSION if is_installed_build() else f"{VERSION} (from source)"
