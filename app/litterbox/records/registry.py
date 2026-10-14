"""
registry.py - the part-number records.

Every part number gets one small YAML file in the repo's PN-logs folder:

    hcr-litterbox/
      PN-logs/
        HCR-00042-001.yaml      <- the record for part number HCR-00042-001
      cad/
        HCR-00042-001.SLDPRT    <- the CAD files that belong to it
        HCR-00042-001.SLDDRW

A record holds the description, status, who created it, and a history of
events (created, checked out, checked in, released, ...).

This file reads and writes records on disk. It does NOT run git. Whoever calls
it (later: create.py and litterbox.py) is responsible for locking, committing
and pushing.

Rules this file enforces:
  * A record is never deleted. A number that has been assigned stays used
    forever. A part that is abandoned is marked "void" and its number is still
    treated as taken.
  * A record can only be created once (two people can't both create the same PN).
  * Status changes follow the rules: in_work -> released -> (reopen) in_work,
    and in_work -> void.
"""

import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from litterbox.core.filenames import parse_filename
from litterbox.core.numbering import next_base, next_variant
from litterbox.core.part_number import PN, PNError, parse, parse_short, try_parse
from litterbox.core.revision_letters import FIRST_REVISION, check_revision, next_revision, revision_number
from litterbox import layout


STATUS_IN_WORK = "in_work"
STATUS_RELEASED = "released"
STATUS_VOID = "void"
ALL_STATUSES = (STATUS_IN_WORK, STATUS_RELEASED, STATUS_VOID)

EVENT_CREATED = "created"
EVENT_CHECKED_OUT = "checked_out"
EVENT_CHECKED_IN = "checked_in"
EVENT_RELEASED = "released"
EVENT_REOPENED = "reopened"
EVENT_VOIDED = "voided"
EVENT_MADE_COTS = "made_cots"
EVENT_EDITED = "edited"
EVENT_REVISED = "revised"
EVENT_REVISION_CANCELLED = "revision_cancelled"
EVENT_RELEASE_REQUESTED = "release_requested"
EVENT_RELEASE_SIGNED = "release_signed"
EVENT_RELEASE_REJECTED = "release_rejected"
EVENT_RELEASE_WITHDRAWN = "release_withdrawn"
EVENT_REASSIGNED = "workflow_reassigned"


class RegistryError(Exception):
    """Something is wrong with a record. The message is safe to show to a user."""


class PNExistsError(RegistryError):
    """Tried to create a record for a part number that already exists."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def now_utc():
    """Current time as text, e.g. '2026-10-04T21:32:10Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_text(value):
    """Turn whatever YAML gave us into plain text.

    If someone hand-edits a record and leaves a timestamp unquoted, YAML turns
    it into a datetime object. We convert it back so the rest of the code only
    ever sees text.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _clean_event(event):
    cleaned = dict(event)
    if "at" in cleaned:
        cleaned["at"] = _as_text(cleaned["at"])
    return cleaned


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------

_KNOWN_FIELDS = {
    "pn", "org", "base", "variant", "revision", "released_revision", "name", "description", "status", "cots",
    "imported", "import_path", "created_by", "created_at", "approvals", "pending", "references", "references_outdated", "history",
}


class _Quoted(str):
    """Text that is always written in quotes ('00001-001'), so YAML can never read it as a number."""


yaml.SafeDumper.add_representer(
    _Quoted, lambda dumper, value: dumper.represent_scalar("tag:yaml.org,2002:str", str(value), style="'"))


@dataclass
class Record:
    pn: PN
    name: str                   # the formal name of the part (required)
    created_by: str
    created_at: str
    description: str = ""       # optional extra context, tags, notes
    revision: str = FIRST_REVISION   # the working (latest) revision
    released_revision: str = ""      # the latest released revision; empty until the first release
    status: str = STATUS_IN_WORK    # the status of the working revision
    cots: bool = False          # a purchased part: can never be checked out
    imported: bool = False      # came in through the importer rather than New Part / New Variant
    import_path: str = ""       # where the file was imported from (only for imported parts)
    approvals: list = field(default_factory=list)   # one entry per completed workflow (see workflow.py): who signed, when, and how it ended
    pending: dict = field(default_factory=dict)     # a request waiting for sign-offs (see workflow.py); empty when there is none
    references_outdated: list = field(default_factory=list)  # revisions whose assembly changed but whose list of parts could not be read
    references: dict = field(default_factory=dict)  # revision -> the parts that revision's assembly uses, e.g. {'A': ['HCR-00005-001_A']}
    history: list = field(default_factory=list)     # list of event dicts
    extra: dict = field(default_factory=dict)       # unknown fields, kept so nothing is lost

    def to_dict(self):
        data = {
            "org": self.pn.org,
            "pn": _Quoted(self.pn.short),   # without the org: it is the line above
            "revision": self.revision,
            "released_revision": self.released_revision,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "cots": self.cots,
            "imported": self.imported,
        }
        if self.import_path:
            data["import_path"] = self.import_path
        data.update({
            "created_by": self.created_by,
            "created_at": self.created_at,
            "approvals": list(self.approvals),
        })
        if self.pending:
            data["pending"] = self.pending
        if self.references_outdated:
            data["references_outdated"] = sorted(self.references_outdated, key=revision_number)
        if self.references:
            data["references"] = {rev: list(stems) for rev, stems in sorted(
                self.references.items(), key=lambda item: revision_number(item[0]))}
        data.update({
            "history": [dict(e) for e in self.history],
        })
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data):
        if "pn" not in data:
            raise RegistryError("The record has no 'pn' field.")
        try:
            if data.get("org") is not None:
                pn = parse_short(str(data["pn"]), str(data["org"]))
            else:
                pn = parse(str(data["pn"]))
        except PNError as e:
            raise RegistryError(f"The record has an invalid 'pn' or 'org' field. {e}")

        try:
            revision = check_revision(data.get("revision", FIRST_REVISION))
            released_revision = _as_text(data.get("released_revision")).strip()
            if released_revision:
                released_revision = check_revision(released_revision)
        except PNError as e:
            raise RegistryError(f"{pn}: {e}")
        if released_revision and revision_number(released_revision) > revision_number(revision):
            raise RegistryError(f"{pn}: the released revision ({released_revision}) is later than the "
                                f"working revision ({revision}).")

        status = _as_text(data.get("status", STATUS_IN_WORK))
        if status not in ALL_STATUSES:
            raise RegistryError(f"{pn}: unknown status '{status}'.")

        history = data.get("history") or []
        if not isinstance(history, list) or not all(isinstance(e, dict) for e in history):
            raise RegistryError(f"{pn}: 'history' must be a list of events.")

        approvals = data.get("approvals") or []
        if not isinstance(approvals, list):
            raise RegistryError(f"{pn}: 'approvals' must be a list.")

        pending = data.get("pending") or {}
        if not isinstance(pending, dict):
            raise RegistryError(f"{pn}: 'pending' must be a request with its sign-offs.")
        if pending:
            for key in ("id", "action", "revision", "requested_by", "template", "signoffs", "slots"):
                if key not in pending:
                    raise RegistryError(f"{pn}: the pending request has no '{key}'.")
            if (not isinstance(pending["signoffs"], list) or not isinstance(pending["template"], dict)
                    or not isinstance(pending["slots"], list)):
                raise RegistryError(f"{pn}: the pending request is malformed.")
            pending = {k: (_as_text(v) if k in ("requested_at",) else v) for k, v in pending.items()}
            pending["signoffs"] = [dict(e, at=_as_text(e.get("at"))) if isinstance(e, dict) else e
                                   for e in pending["signoffs"]]

        for key in ("cots", "imported"):
            if not isinstance(data.get(key, False), bool):
                raise RegistryError(f"{pn}: '{key}' must be true or false.")

        references = data.get("references") or {}
        if not isinstance(references, dict):
            raise RegistryError(f"{pn}: 'references' must list the parts used by each revision.")
        clean_refs = {}
        for rev, stems in references.items():
            try:
                rev = check_revision(str(rev))
            except PNError as e:
                raise RegistryError(f"{pn}: bad revision in 'references'. {e}")
            if not isinstance(stems, list) or not all(isinstance(x, str) for x in stems):
                raise RegistryError(f"{pn}: 'references' for Rev {rev} must be a list of part numbers.")
            clean_refs[rev] = list(stems)

        outdated = data.get("references_outdated") or []
        if not isinstance(outdated, list):
            raise RegistryError(f"{pn}: 'references_outdated' must be a list of revisions.")
        try:
            outdated = [check_revision(str(r)) for r in outdated]
        except PNError as e:
            raise RegistryError(f"{pn}: bad revision in 'references_outdated'. {e}")

        name, description = _as_text(data.get("name")), _as_text(data.get("description"))
        if "name" not in data:
            # Records made before parts had a name: the old description becomes the name.
            name, description = description, ""

        return cls(
            pn=pn,
            name=name,
            description=description,
            created_by=_as_text(data.get("created_by")),
            created_at=_as_text(data.get("created_at")),
            revision=revision,
            released_revision=released_revision,
            status=status,
            cots=bool(data.get("cots", False)),
            imported=bool(data.get("imported", False)),
            import_path=_as_text(data.get("import_path")),
            approvals=list(approvals),
            pending=pending,
            references=clean_refs,
            references_outdated=outdated,
            history=[_clean_event(e) for e in history],
            extra={k: v for k, v in data.items() if k not in _KNOWN_FIELDS},
        )


def _dump(record):
    return yaml.safe_dump(
        record.to_dict(), sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=100,
    )


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

def log_dir(repo):
    return Path(repo) / layout.LOG_DIR_NAME


def cad_dir(repo):
    return Path(repo) / layout.CAD_DIR_NAME


def cancelled_dir(repo):
    return Path(repo) / layout.CANCELLED_DIR_NAME


def record_path(repo, pn):
    return log_dir(repo) / f"{pn}.yaml"


# ---------------------------------------------------------------------------
# Reading, creating, saving
# ---------------------------------------------------------------------------

def record_relpath(pn):
    """Where a PN's record lives, relative to the repo, with forward slashes."""
    return f"{layout.LOG_DIR_NAME}/{pn}.yaml"


def _read(path, expected_pn):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)      # safe_load only: never plain yaml.load
    except (OSError, yaml.YAMLError) as e:
        raise RegistryError(f"Could not read {path.name}: {e}")
    if not isinstance(data, dict):
        raise RegistryError(f"{path.name} is empty or not a valid record.")
    record = Record.from_dict(data)
    if record.pn != expected_pn:
        raise RegistryError(
            f"{path.name} is named {expected_pn} but its contents say {record.pn}."
        )
    return record


def load(repo, pn):
    """Load the record for a PN. Raises RegistryError if it doesn't exist."""
    path = record_path(repo, pn)
    if not path.is_file():
        raise RegistryError(f"There is no record for {pn}.")
    return _read(path, pn)


def exists(repo, pn):
    return record_path(repo, pn).is_file()


def create_record(repo, pn, name, created_by, description="", cots=False, imported=False, import_path=""):
    """Create the record file for a brand-new PN and return the Record.

    The name is required. The description is optional. import_path is only kept
    for imported parts. Raises PNExistsError if that PN already has a record, so
    an existing record can never be overwritten.
    """
    name = (name or "").strip()
    description = (description or "").strip()
    created_by = (created_by or "").strip()
    if not name:
        raise RegistryError("A name is required.")
    if not created_by:
        raise RegistryError("Could not tell who is creating this part. Set your name in git "
                            "(git config user.name).")

    record = Record(pn=pn, name=name, description=description, created_by=created_by, created_at=now_utc(),
                    cots=bool(cots), imported=bool(imported),
                    import_path=(str(import_path).strip() if imported else ""))
    add_event(record, EVENT_CREATED, created_by)
    record.history[-1]["at"] = record.created_at    # created event and created_at match exactly

    path = record_path(repo, pn)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Mode "x" means "create, but fail if the file already exists".
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(_dump(record))
    except FileExistsError:
        raise PNExistsError(f"{pn} already exists.")
    except OSError as e:
        raise RegistryError(f"Could not create the record for {pn}: {e}")
    return record


def save(repo, record):
    """Write changes to an existing record.

    The record file is read-only on disk unless you hold its lock, so a save
    without the lock fails here with a clear message instead of a confusing error.
    """
    path = record_path(repo, record.pn)
    if not path.is_file():
        raise RegistryError(f"There is no record for {record.pn} to save. Use create_record().")
    if not os.access(path, os.W_OK):
        raise RegistryError(
            f"The record for {record.pn} is read-only. Check the part out first so you hold its lock."
        )

    text = _dump(record)
    tmp_path = None
    try:
        # Write to a temporary file first, then swap it in, so a crash can't leave
        # a half-written record behind.
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError as e:
        raise RegistryError(f"Could not save the record for {record.pn}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------------------------------------------------------------------------
# Listing what exists
# ---------------------------------------------------------------------------

def list_pns(repo, org=None):
    """Every PN that has a record, sorted. Files that aren't records are ignored."""
    folder = log_dir(repo)
    if not folder.is_dir():
        return []
    found = set()
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() == ".yaml":
            pn = try_parse(path.stem)
            if pn and (org is None or pn.org == str(org).upper()):
                found.add(pn)
    return sorted(found)


def used_bases(repo, org=None):
    """Set of base numbers that are taken (including void ones)."""
    return {pn.base for pn in list_pns(repo, org)}


def used_variants(repo, base, org=None):
    """Set of variant numbers that are taken for one base number."""
    return {pn.variant for pn in list_pns(repo, org) if pn.base == base}


def next_free_base(repo, org=None, start=1):
    """The lowest base number nobody has used yet, at or above `start`."""
    return next_base(used_bases(repo, org), start)


def next_free_variant(repo, base, org=None):
    """The lowest unused variant number for a base (1 if the base is brand new)."""
    return next_variant(used_variants(repo, base, org))


def load_variants(repo, base, org=None):
    """The records of every variant of one base, in order. For the New Variant dialog."""
    return [load(repo, pn) for pn in list_pns(repo, org) if pn.base == base]


def cad_index(repo):
    """Scan the cad folder once. Returns {PN: {revision: [relative paths]}} for every file in it.

    Paths are relative to the repo with forward slashes, which is what git
    wants, for example {'A': ['cad/HCR-00042-001_A.SLDDRW', 'cad/HCR-00042-001_A.SLDPRT']}.
    Files that aren't named like Litterbox files (~$ temp files, notes) are ignored.
    """
    index = {}
    folder = cad_dir(repo)
    if not folder.is_dir():
        return index
    for path in folder.iterdir():
        if not path.is_file():
            continue
        try:
            file_pn, revision, _ext = parse_filename(path.name)
        except PNError:
            continue
        index.setdefault(file_pn, {}).setdefault(revision, []).append(f"{layout.CAD_DIR_NAME}/{path.name}")
    for revisions in index.values():
        for files in revisions.values():
            files.sort()
    return index


def cad_files(repo, pn, revision=None):
    """The CAD files in the cad folder for one revision of a PN (see cad_index).

    Without `revision` it is the part's working (latest) revision, read from its record.
    """
    if revision is None:
        revision = load(repo, pn).revision
    return cad_index(repo).get(pn, {}).get(check_revision(revision), [])


def all_cad_files(repo, pn):
    """Every CAD file of every revision of a PN, sorted."""
    return sorted(f for files in cad_index(repo).get(pn, {}).values() for f in files)


# ---------------------------------------------------------------------------
# History events and status changes
#
# These change the Record in memory only. After calling one, call save().
# ---------------------------------------------------------------------------

def add_event(record, event, by, **details):
    """Append an event to the record's history and return it."""
    by = (by or "").strip()
    if not by:
        raise RegistryError("An event must say who did it.")
    entry = {"event": event, "by": by, "at": now_utc(), "revision": record.revision}
    entry.update({key: value for key, value in details.items() if value is not None})
    record.history.append(entry)
    return entry


def _require_status(record, wanted, action):
    if record.status != wanted:
        raise RegistryError(
            f"Cannot {action} {record.pn}: its status is '{record.status}', not '{wanted}'."
        )


def _require_reason(reason, action):
    reason = (reason or "").strip()
    if not reason:
        raise RegistryError(f"A reason is required to {action}.")
    return reason


def _require_not_pending(record, action):
    if record.pending:
        raise RegistryError(f"Cannot {action} {record.pn}: it is waiting for sign-offs. "
                            "Withdraw the request first.")


def record_checkout(record, by, files):
    """Log a check-out. Released, void and COTS parts can't be checked out."""
    _require_status(record, STATUS_IN_WORK, "check out")
    _require_not_pending(record, "check out")
    if record.cots:
        raise RegistryError(f"Cannot check out {record.pn}: it is a COTS (purchased) part.")
    return add_event(record, EVENT_CHECKED_OUT, by, files=list(files))


def set_references(record, stems, revision=None):
    """Remember which parts this revision's assembly uses (a list like ['HCR-00005-001_A'], possibly
    empty). Also clears the 'out of date' mark. Returns True if anything changed."""
    revision = revision or record.revision
    stems = sorted(set(stems), key=str.lower)
    changed = record.references.get(revision) != stems
    record.references[revision] = stems
    if revision in record.references_outdated:
        record.references_outdated.remove(revision)
        changed = True
    return changed


def references_need_update(record, revision, files):
    """True if the list of parts used by this revision of an assembly can't be trusted: it has an assembly
    file (in `files`) and either was never read or has changed since it was last read."""
    if record.cots or record.status == STATUS_VOID:
        return False
    if not any(str(f).lower().endswith(".sldasm") for f in files):
        return False
    return revision not in record.references or revision in record.references_outdated


def record_checkin(record, by, files, comment="", references=None):
    """Log a check-in. `references` (a list, or None for 'not read this time') updates what the
    working revision uses; the event lists them when they changed. If an assembly file was checked
    in and the references could not be read, the revision is marked as needing an update."""
    changed = set_references(record, references) if references is not None else False
    if references is None and any(str(f).lower().endswith(".sldasm") for f in files):
        if record.revision not in record.references_outdated:
            record.references_outdated.append(record.revision)
    return add_event(record, EVENT_CHECKED_IN, by, files=list(files),
                     comment=(comment or "").strip() or None,
                     references=list(record.references.get(record.revision, [])) if changed else None)


def mark_released(record, by, files, **details):
    """in_work -> released. `files` is the list of files being frozen. Extra details (who signed off, an
    override reason...) go on the history event. This does not look at a pending request: workflow.py,
    which owns those, clears it."""
    _require_status(record, STATUS_IN_WORK, "release")
    if record.cots:
        raise RegistryError(f"Cannot release {record.pn}: it is a COTS (purchased) part.")
    record.status = STATUS_RELEASED
    record.released_revision = record.revision
    return add_event(record, EVENT_RELEASED, by, files=list(files), **details)


def edit_details(record, by, name, description):
    """Change the name and/or description. Returns the history entry, or None if nothing changed.

    The caller must hold the record's lock (the part is checked out). The history entry lists
    what changed, e.g. changes: ["name: 'Bracket' -> 'Bracket, left'"].
    """
    name = " ".join((name or "").split())
    description = " ".join((description or "").split())
    if not name:
        raise RegistryError("A name is required.")
    changes = []
    if name != record.name:
        changes.append(f"name: '{record.name}' -> '{name}'")
    if description != record.description:
        changes.append(f"description: '{record.description}' -> '{description}'")
    if not changes:
        return None
    record.name, record.description = name, description
    return add_event(record, EVENT_EDITED, by, changes=changes)


def mark_cots(record, by, files):
    """Turn an in-work part into a COTS (purchased) part. `files` is the list of files it covers."""
    _require_status(record, STATUS_IN_WORK, "make COTS")
    _require_not_pending(record, "make COTS")
    if record.cots:
        raise RegistryError(f"{record.pn} is already a COTS part.")
    if record.released_revision or record.revision != FIRST_REVISION:
        raise RegistryError(f"Cannot make {record.pn} COTS: it has been released or revised, so it is "
                            "not an unmodified purchased part.")
    record.cots = True
    return add_event(record, EVENT_MADE_COTS, by, files=list(files))


def cancelled_revisions(record):
    """Revision letters that were cancelled. They are never used again."""
    return [e["cancelled"] for e in record.history
            if e.get("event") == EVENT_REVISION_CANCELLED and e.get("cancelled")]


def next_free_revision(record):
    """The letter a revise would use: the one after the working revision, skipping cancelled ones."""
    return next_revision(record.revision, skip=cancelled_revisions(record))


def can_revise(record):
    """'' if the part can be revised, else the reason it can't."""
    if record.pending:
        return "It is waiting for sign-offs."
    if record.cots:
        return "It is a COTS (purchased) part, which is never revised."
    if record.status != STATUS_RELEASED:
        return f"Its status is '{record.status}'. Only a released part can be revised."
    return ""


def mark_revised(record, by, reason, files):
    """released -> a new working revision (in_work). `files` are the new revision's files."""
    problem = can_revise(record)
    if problem:
        raise RegistryError(f"Cannot revise {record.pn}. {problem}")
    reason = _require_reason(reason, "revise a part")
    previous = record.revision
    record.revision = next_free_revision(record)
    if previous in record.references:                   # the copy uses the same parts the original did
        record.references[record.revision] = list(record.references[previous])
        if previous in record.references_outdated:
            record.references_outdated.append(record.revision)
    record.status = STATUS_IN_WORK
    return add_event(record, EVENT_REVISED, by, from_revision=previous, reason=reason, files=list(files))


def can_cancel_revision(record):
    """'' if the working revision can be cancelled, else the reason it can't."""
    if record.status != STATUS_IN_WORK:
        return f"Its status is '{record.status}'. Only a revision that is still in work can be cancelled."
    if not record.released_revision:
        return f"Rev {record.revision} was never released, so there is no earlier revision to go back to. Use Void."
    if revision_number(record.released_revision) >= revision_number(record.revision):
        return "The working revision is the released one. Use Unrelease instead."
    return ""


def mark_revision_cancelled(record, by, reason, files):
    """in_work revision -> gone; the part goes back to its latest released revision.
    `files` are the names the cancelled revision's files were kept under."""
    _require_not_pending(record, "cancel the revision of")
    problem = can_cancel_revision(record)
    if problem:
        raise RegistryError(f"Cannot cancel the revision of {record.pn}. {problem}")
    reason = _require_reason(reason, "cancel a revision")
    cancelled = record.revision
    record.references.pop(cancelled, None)
    if cancelled in record.references_outdated:
        record.references_outdated.remove(cancelled)
    record.revision = record.released_revision
    record.status = STATUS_RELEASED
    return add_event(record, EVENT_REVISION_CANCELLED, by, cancelled=cancelled, reason=reason, files=list(files))


def _earlier_released_revision(record):
    """The latest revision released before the working one (empty if there was none)."""
    earlier = [e.get("revision") for e in record.history
               if e.get("event") == EVENT_RELEASED and e.get("revision") and e.get("revision") != record.revision]
    return max(earlier, key=revision_number, default="")


def mark_reopened(record, by, reason):
    """released -> in_work, or COTS -> a normal in-work part. A reason is required."""
    _require_not_pending(record, "reopen")
    was_cots = record.status == STATUS_IN_WORK and record.cots
    if not was_cots:
        _require_status(record, STATUS_RELEASED, "reopen")
    reason = _require_reason(reason, "reopen a part")
    record.status = STATUS_IN_WORK
    if not was_cots:
        record.released_revision = _earlier_released_revision(record)
    record.cots = False
    return add_event(record, EVENT_REOPENED, by, reason=reason, was_cots=True if was_cots else None)


def mark_void(record, by, reason):
    """in_work -> void. The number stays used forever. A reason is required.

    Only a part that has never been released can be voided. Once a revision has been released
    the part can't disappear: an unwanted new revision is cancelled instead."""
    _require_status(record, STATUS_IN_WORK, "void")
    _require_not_pending(record, "void")
    if record.released_revision:
        raise RegistryError(f"Cannot void {record.pn}: Rev {record.released_revision} was released. "
                            "Use Cancel Revision to throw away the revision that is in work.")
    reason = _require_reason(reason, "void a part")
    record.status = STATUS_VOID
    return add_event(record, EVENT_VOIDED, by, reason=reason)
