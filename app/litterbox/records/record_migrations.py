"""
record_migrations.py - bringing records written in an older record format up to the current one.

A record says its format (`format: 1`; a record without one is 1). When a release changes the shape of a record in a
way an older Litterbox would misread (a field renamed, restructured, or meaning something new), it adds a Step here,
which raises the format by one. Adding a field an older Litterbox can ignore needs no step: unknown fields are kept
(record_model.Record.extra).

- Reading: Record.from_dict runs the steps a record needs (upgrade), so an old record is read in the current shape
  without being rewritten. Saving it writes the current format.
- Writing: an older Litterbox refuses a record in a newer format, so this one writes the current format only in a
  vault whose min_litterbox_version is at least the version that brought it in (writes_need). Until an Admin raises
  it with Vault > Upgrade records... (vault/record_upgrade.py), record_store refuses to write records (may_write).
  vault/config.apply tells this module how to read the vault's minimum (configure), as it tells core/part_number
  its digits. It is read as each record is written, after the action has fetched the latest, so an upgrade someone
  else has just uploaded counts at once.

A step's change gets its own copy of a record as read from YAML, in the step's format, and returns the record in the
next format (upgrade sets `format`). It must keep the fields it doesn't know, and running it on a record already in
the new shape must change nothing (a record edited by hand halfway, say). tests/records/fixtures/ holds old records
that every step is tested on.
"""

import copy
from dataclasses import dataclass
from typing import Callable

from litterbox import version


@dataclass(frozen=True)
class Step:
    since: str                  # the first Litterbox version that writes the new format, e.g. "0.6.0"
    what: str                   # what changes, in plain words, for the Upgrade records question
    change: Callable            # change(data) -> data: a record dict in the old format, in the new format


# {old format: the Step to old format + 1}, with no gaps: 1, 2, 3, ... The current format is one more than the last.
STEPS = {}

# Functions giving the vault's min_litterbox_version ("" for none), from vault/config.apply: as it is on disk now, and
# as the vault's server has it (asked only when the one on disk doesn't allow writing). Change them only through
# configure().
READ_MINIMUM = None
READ_LATEST_MINIMUM = None


def current_format():
    """The record format this Litterbox writes."""
    return 1 + len(STEPS)


def stored_format(data):
    """The format a record's YAML says it is in (1 without one), or None if it isn't a whole number of 1 or more."""
    value = data.get("format", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def upgrade(data):
    """`data` (a record as read from YAML, in a format no newer than the current one) in the current format, as a
    new dict. A record already in it comes back as it is, not copied: every record is read on every refresh."""
    first = stored_format(data) or 1
    if first >= current_format():
        return data
    for old in range(first, current_format()):
        data = STEPS[old].change(copy.deepcopy(data))
        data["format"] = old + 1
    return data


def steps_for(data):
    """The steps a record needs, oldest first."""
    return [STEPS[old] for old in range(stored_format(data) or 1, current_format())]


def writes_need():
    """The oldest Litterbox a vault must require before this one may write records there; "" if any may."""
    return STEPS[current_format() - 1].since if STEPS else ""


def configure(read_minimum, read_latest_minimum=None):
    """Note how to read the vault's min_litterbox_version (vault/config.apply): read_minimum() gives it as it is on
    disk, read_latest_minimum() as the vault's server has it."""
    global READ_MINIMUM, READ_LATEST_MINIMUM
    READ_MINIMUM, READ_LATEST_MINIMUM = read_minimum, read_latest_minimum


def may_write(ask_server=True):
    """May records be written in this vault? Only once it requires a Litterbox that reads the current format. If the
    copy on disk doesn't, the vault's server is asked (unless ask_server is False): an Admin may have upgraded it since
    this copy last got the latest, and an action's own upload brings that in before its commit goes up."""
    needed = writes_need()
    if not needed:
        return True
    readers = [READ_MINIMUM] + ([READ_LATEST_MINIMUM] if ask_server else [])
    return any(_requires(reader, needed) for reader in readers if reader is not None)


def _requires(read, needed):
    minimum = str(read() or "").lstrip("vV")
    try:
        return bool(minimum) and version.parse(minimum) >= version.parse(needed)
    except ValueError:
        return False
