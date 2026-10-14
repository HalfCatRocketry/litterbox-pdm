"""
reference_model.py - one use of a part by an assembly revision (Use), and its state: ok, stale,
unreleased, cancelled, void or missing. Plus reading part numbers out of file stems, and a lazy record cache.
"""

from dataclasses import dataclass

from litterbox.core import filenames
from litterbox.core import revision_letters
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store


# Why a reference is flagged
OK = "ok"


STALE = "stale"                 # a newer revision of the part has been released


UNRELEASED = "unreleased"       # the revision used is not released yet


CANCELLED = "cancelled"         # the revision used was cancelled: its files are gone from cad


VOID = "void"


MISSING = "missing"             # there is no record for the part


STATE_TEXT = {
    OK: "OK",
    STALE: "Newer revision released",
    UNRELEASED: "Not released yet",
    CANCELLED: "Revision was cancelled",
    VOID: "Part was voided",
    MISSING: "Part not found",
}


# Release rule (config.yaml: release_rule)
RULE_WARN, RULE_BLOCK, RULE_OFF = "warn", "block", "off"


class ReferencesError(LitterboxError):
    """Something went wrong reading or changing references."""


def split_stem(stem):
    """'HCR-00005-001_B' -> (PN, 'B'), or None if it is not a Litterbox name."""
    parsed = filenames.try_parse_filename(f"{stem}.X")
    if parsed is None:
        return None
    return parsed[0], parsed[1]


def stem_of_path(path):
    """The Litterbox 'HCR-00005-001_B' of a file path, or None for any other file."""
    parsed = filenames.try_parse_filename(str(path))
    if parsed is None:
        return None
    return filenames.file_stem(parsed[0], parsed[1])


class LazyRecords:
    """Looks records up by PN as they are needed (None for a missing or unreadable one)."""

    def __init__(self, repo):
        self.repo, self.cache = repo, {}

    def get(self, pn, default=None):
        if pn not in self.cache:
            try:
                self.cache[pn] = record_store.load(self.repo, pn)
            except record_model.RegistryError:
                self.cache[pn] = None
        return self.cache[pn] or default


def load_records(repo):
    """{PN: Record} for every readable record."""
    records = {}
    for pn in record_store.list_pns(repo):
        try:
            records[pn] = record_store.load(repo, pn)
        except record_model.RegistryError:
            continue
    return records


@dataclass
class Use:
    """One reference: `parent` (at `parent_revision`) uses `child` at `child_revision`."""
    parent: PN
    parent_revision: str
    child: PN
    child_revision: str
    state: str                      # OK, STALE, ...
    latest_released: str = ""       # the child's latest released revision ('' if none)
    parent_name: str = ""
    child_name: str = ""
    parent_status: str = ""         # status of THAT revision of the parent: in_work / released
    editable: bool = False          # the parent revision is in work, so it can be pointed at a newer part

    @property
    def state_text(self):
        text = STATE_TEXT[self.state]
        if self.state == STALE:
            text += f" (Rev {self.latest_released})"
        return text

    @property
    def replaceable(self):
        """Can Litterbox point this reference at the child's latest released revision?"""
        return (self.editable and bool(self.latest_released)
                and self.state in (STALE, CANCELLED)
                and self.latest_released != self.child_revision)


def classify(child_record, revision):
    """(state, latest released revision) of one use of a part at one revision."""
    if child_record is None:
        return MISSING, ""
    latest = child_record.released_revision
    if child_record.status == record_model.STATUS_VOID:
        return VOID, latest
    if revision in record_revisions.cancelled_revisions(child_record):
        return CANCELLED, latest
    number = revision_letters.revision_number(revision)
    if latest and revision_letters.revision_number(latest) > number:
        return STALE, latest
    if not latest or number > revision_letters.revision_number(latest):
        if child_record.cots:
            return OK, latest
        return UNRELEASED, latest
    return OK, latest
