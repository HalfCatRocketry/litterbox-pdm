"""
record_model.py - what a part record holds: the Record class, the statuses and history event names, and how
a record is written as YAML and read back.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import yaml

from litterbox.core.part_number import PN, PNError, parse, parse_short
from litterbox.core.revision_letters import FIRST_REVISION, check_revision, revision_number


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


def dump(record):
    return yaml.safe_dump(
        record.to_dict(), sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=100,
    )
