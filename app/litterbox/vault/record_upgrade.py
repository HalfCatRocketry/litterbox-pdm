"""
record_upgrade.py - Vault > Upgrade records...: bringing a vault's part and document records up to the record format
this Litterbox writes (records/record_migrations.py), for everyone.

Until it is done, this Litterbox reads the vault's old records in the new shape but writes none
(record_store.check_may_write), so after each refresh an Admin or the Owner is asked (gui/main_window/
record_upgrading.py) and anyone else is told an Admin needs to. Upgrading is two uploads:

1. Raise the vault's min_litterbox_version to the version that brought the format in (record_migrations.writes_need),
   under the settings lock. Older copies of Litterbox, which can't read the new format, are then told to update, and
   this Litterbox may write records. This alone unblocks everyone.
2. Rewrite every old record in the new format, in one commit (parts/batch_core.edit_records). A record someone has
   checked out is skipped: its lock is theirs, and it is written in the new format when they check it in. If this
   upload fails, nothing is lost (old records are still read correctly), and Upgrade records... can be run again.
"""

from dataclasses import dataclass, field

import yaml

from litterbox import layout
from litterbox import version
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.parts import batch_core
from litterbox.records import record_migrations
from litterbox.records import record_store
from litterbox.team import team_permissions
from litterbox.util import fast_yaml
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.vault import shared_files

PERMISSION = "manage_settings"


@dataclass
class Plan:
    """What Upgrade records would do, for the question before it."""
    outdated: dict = field(default_factory=dict)        # {pn: the format its record is in}
    checked_out: list = field(default_factory=list)     # those of them someone has checked out: skipped
    steps: list = field(default_factory=list)           # [(Step, how many records it changes)], oldest first
    raise_minimum: str = ""                             # the min_litterbox_version it sets ("" if it already is)


def outdated(repo):
    """{pn or document number: its record's format} for every record in an older format than this Litterbox writes.
    Empty at once when this Litterbox has no upgrade steps. A record that can't be read is left out (it is reported
    wherever it is read)."""
    if not record_migrations.STEPS:
        return {}
    found = {}
    for pn in [*record_store.list_pns(repo), *record_store.list_docs(repo)]:
        try:
            data = fast_yaml.safe_load(record_store.record_path(repo, pn).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):                    # a broken record is reported wherever it is read
            continue
        if not isinstance(data, dict):
            continue
        stored = record_migrations.stored_format(data)
        if stored is not None and stored < record_migrations.current_format():
            found[pn] = stored
    return found


def needs_upgrade(repo):
    """True if this vault's records need Upgrade records: some are old, or records can't be written yet."""
    return bool(outdated(repo)) or not record_migrations.may_write(ask_server=False)


def _minimum_to_set(repo):
    """The min_litterbox_version Upgrade records must set, or "" if the vault already requires it."""
    needed = record_migrations.writes_need()
    if not needed:
        return ""
    current = config.load(repo).get("min_litterbox_version")
    try:
        if current and version.parse(str(current)) >= version.parse(needed):
            return ""
    except ValueError:
        pass
    return needed


def _locked_paths(repo):
    return set(lfs_locks.get_locks(repo, strict=True))


def plan(repo):
    """What Upgrade records would change (reads the lock list from the host)."""
    old = outdated(repo)
    locked = _locked_paths(repo) if old else set()
    counts = {}
    for stored in old.values():
        for old_format in range(stored, record_migrations.current_format()):
            counts[old_format] = counts.get(old_format, 0) + 1
    return Plan(outdated=old,
                checked_out=sorted((pn for pn in old if record_store.record_relpath(pn).lower() in locked), key=str),
                steps=[(record_migrations.STEPS[n], counts[n]) for n in sorted(counts)],
                raise_minimum=_minimum_to_set(repo))


def _raise_minimum(repo, minimum):
    """Upload 1: the vault requires `minimum`, so records may be written in the current format."""
    def change():
        if not _minimum_to_set(repo):                       # someone else did it meanwhile
            return [], "", False
        config_write.stamp(repo, minimum)
        message = (f"Vault needs Litterbox {minimum}: records in format {record_migrations.current_format()}")
        return [layout.CONFIG_PATH], message, True
    shared_files.edit(repo, [layout.CONFIG_PATH], "the vault settings", change)
    config.apply(repo)                                      # this Litterbox may now write records here


class AlreadyUpgraded(LitterboxError):
    """Someone else upgraded this record while the upgrade was starting: nothing to do."""


@dataclass
class Result:
    rewritten: int = 0                                  # records written in the new format
    checked_out: list = field(default_factory=list)     # skipped: someone has them checked out
    errors: dict = field(default_factory=dict)          # {pn: why} for the others that couldn't be done


def upgrade(repo):
    """Upgrade the vault's records (see the docstring at the top) and return a Result. Raises LitterboxError if you
    may not, or an upload fails."""
    team_permissions.require(repo, PERMISSION)
    minimum = _minimum_to_set(repo)
    if minimum:
        _raise_minimum(repo, minimum)                   # gets the latest first
    old = outdated(repo)
    if not old:
        return Result()
    locked = _locked_paths(repo)
    result = Result(checked_out=sorted((pn for pn in old if record_store.record_relpath(pn).lower() in locked),
                                       key=str))
    target = record_migrations.current_format()

    def rewrite(record, user):
        """Loading the record upgraded it, and saving it writes the new format: unless, after the latest was
        fetched, its file is in the new format already."""
        if record.pn not in outdated_now():
            raise AlreadyUpgraded(f"{record.pn} is upgraded already.")

    def outdated_now():
        if not cache:
            cache.append(outdated(repo))                # read once, after the batch has fetched the latest
        return cache[0]

    cache = []
    items = [(pn, PERMISSION, rewrite, f"{pn}: Record upgraded to format {target}")
             for pn in sorted(old, key=str) if pn not in result.checked_out]
    if not items:
        return result
    batch = batch_core.edit_records(repo, items)
    result.rewritten = sum(1 for done in batch.results.values() if done)
    result.errors = {pn: str(e) for pn, e in batch.errors.items() if not isinstance(e, AlreadyUpgraded)}
    return result
