"""
record_model.py - what a part record holds: the Record class, the statuses and history event names, and how
a record is written as YAML and read back.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import yaml

from litterbox.core import doc_number
from litterbox.core.doc_number import DocNumber
from litterbox.core.part_number import PN, PNError, parse, parse_short
from litterbox.core.revision_letters import FIRST_REVISION, check_revision, revision_number
from litterbox.records import purchasing_info
from litterbox.records import record_materials
from litterbox.records import record_migrations
from litterbox.records import record_other_files


STATUS_IN_WORK = "in_work"

STATUS_RELEASED = "released"

STATUS_VOID = "void"

ALL_STATUSES = (STATUS_IN_WORK, STATUS_RELEASED, STATUS_VOID)

KIND_CAD = "cad"            # a part or assembly with SolidWorks files (every record before 0.5.1)
KIND_NONCAD = "noncad"      # no CAD files: paint, raw stock, a kit put together in its BOM (bom_items)
ALL_KINDS = (KIND_CAD, KIND_NONCAD)
KIND_LABEL = {KIND_CAD: "CAD", KIND_NONCAD: "Non-CAD"}

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

EVENT_CHECKOUT_BROKEN = "checkout_broken"       # an Admin took a part back from whoever had it checked out

EVENT_PURCHASING_EDITED = "purchasing_edited"   # supplier, cost or lead time changed (records/purchasing_info.py)

EVENT_FILES_MADE = "files_made"         # Litterbox made the STEP and/or PDF of a revision (records/record_exports.py)


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
    "format", "pn", "org", "base", "variant", "revision", "released_revision", "name", "description", "project", "status", "cots",
    "imported", "import_path", "created_by", "created_by_id", "created_at", "approvals", "pending", "draft", "references", "references_outdated", "history",
    "purchasing", "quantities", "exports", "kind", "bom_items", "documents", "number", "doc_type", "materials",
    "other_files",
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
    created_by_id: str = ""     # the creator's id on the team list ("" without one, and in records before 0.4.2)
    description: str = ""       # optional extra context, tags, notes
    project: str = ""           # the project whose block of part numbers it is in (core/projects.py); "" for none
    revision: str = FIRST_REVISION   # the working (latest) revision
    released_revision: str = ""      # the latest released revision; empty until the first release
    status: str = STATUS_IN_WORK    # the status of the working revision
    cots: bool = False          # a purchased part: can never be checked out
    kind: str = KIND_CAD        # KIND_CAD or KIND_NONCAD (a record without CAD files)
    imported: bool = False      # came in through the importer rather than New Part / New Variant
    import_path: str = ""       # where the file was imported from (only for imported parts)
    approvals: list = field(default_factory=list)   # one entry per completed workflow (see workflow.py): who signed, when, and how it ended
    pending: dict = field(default_factory=dict)     # a request waiting for sign-offs (see workflow.py); empty when there is none
    draft: dict = field(default_factory=dict)       # a rejected request being changed by whoever asked (workflow_drafts.py)
    references_outdated: list = field(default_factory=list)  # revisions whose assembly changed but whose list of parts could not be read
    references: dict = field(default_factory=dict)  # revision -> the parts that revision's assembly uses, e.g. {'A': ['HCR-00005-001_A']}
    quantities: dict = field(default_factory=dict)  # revision -> how many of each it uses, e.g. {'A': {'HCR-00005-001_A': 4}}
    bom_items: dict = field(default_factory=dict)   # revision -> BOM lines added by hand, not in a model, as quantities
    history: list = field(default_factory=list)     # list of event dicts
    purchasing: dict = field(default_factory=dict)  # supplier, cost, lead time (records/purchasing_info.py); {} for none
    exports: dict = field(default_factory=dict)     # revision -> the STEP and PDF Litterbox made (records/record_exports.py)
    documents: dict = field(default_factory=dict)   # revision -> the documents linked to it, e.g. {'A': ['PROP-0001']}
    materials: dict = field(default_factory=dict)   # revision -> its material from SolidWorks (records/record_materials.py)
    other_files: dict = field(default_factory=dict)  # revision -> files it uses that aren't parts (record_other_files.py)
    doc_type: str = ""          # a document's type key (documents/doc_types.py); "" for a part
    extra: dict = field(default_factory=dict)       # unknown fields, kept so nothing is lost

    @property
    def is_document(self):
        """True for a document's record (numbered like PROP-0001, in DOC-logs/), False for a part's."""
        return isinstance(self.pn, DocNumber)

    @property
    def uses_cad(self):
        """True for a CAD part (it should have SolidWorks files); False for a non-CAD part or a document."""
        return self.kind == KIND_CAD and not self.is_document

    def to_dict(self):
        if self.is_document:
            data = {"format": record_migrations.current_format(), "number": str(self.pn), "doc_type": self.doc_type}
        else:
            data = {"format": record_migrations.current_format(), "org": self.pn.org,
                    "pn": _Quoted(self.pn.short)}   # without the org: it is the line above
        data.update({
            "revision": self.revision,
            "released_revision": self.released_revision,
            "name": self.name,
            "description": self.description,
        })
        if self.project:
            data["project"] = self.project
        data.update({
            "status": self.status,
            "cots": self.cots,
            "imported": self.imported,
        })
        if self.kind != KIND_CAD:
            data["kind"] = self.kind
        if self.import_path:
            data["import_path"] = self.import_path
        if self.purchasing:
            data["purchasing"] = dict(self.purchasing)
        data.update({
            "created_by": self.created_by,
            **({"created_by_id": self.created_by_id} if self.created_by_id else {}),
            "created_at": self.created_at,
            "approvals": list(self.approvals),
        })
        if self.pending:
            data["pending"] = self.pending
        if self.draft:
            data["draft"] = self.draft
        if self.references_outdated:
            data["references_outdated"] = sorted(self.references_outdated, key=revision_number)
        if self.references:
            data["references"] = {rev: list(stems) for rev, stems in sorted(
                self.references.items(), key=lambda item: revision_number(item[0]))}
        if self.quantities:
            data["quantities"] = {rev: dict(sorted(counts.items(), key=lambda item: item[0].lower()))
                                  for rev, counts in sorted(self.quantities.items(),
                                                            key=lambda item: revision_number(item[0]))}
        if self.other_files:
            data["other_files"] = record_other_files.to_data(dict(sorted(
                self.other_files.items(), key=lambda item: revision_number(item[0]))))
        if self.bom_items:
            data["bom_items"] = {rev: dict(sorted(counts.items(), key=lambda item: item[0].lower()))
                                 for rev, counts in sorted(self.bom_items.items(),
                                                           key=lambda item: revision_number(item[0]))}
        if self.documents:
            data["documents"] = {rev: list(numbers) for rev, numbers in sorted(
                self.documents.items(), key=lambda item: revision_number(item[0]))}
        if self.exports:
            data["exports"] = {rev: dict(made) for rev, made in sorted(
                self.exports.items(), key=lambda item: revision_number(item[0]))}
        if self.materials:
            data["materials"] = dict(sorted(self.materials.items(), key=lambda item: revision_number(item[0])))
        data.update({
            "history": [dict(e) for e in self.history],
        })
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data):
        if "pn" not in data and "number" not in data:
            raise RegistryError("The record has no 'pn' field.")
        if "pn" not in data:
            data = dict(data, pn=data["number"])
        record_format = record_migrations.stored_format(data)     # records written before 0.4.2 have none: 1
        if record_format is None:
            raise RegistryError(f"{data['pn']}: 'format' must be a whole number, 1 or higher.")
        if record_format > record_migrations.current_format():
            raise RegistryError(f"{data['pn']}: this record was written by a newer Litterbox (record format "
                                f"{record_format}). Update Litterbox to read it.")
        data = record_migrations.upgrade(data)              # an older record is read in the current shape
        try:
            if "number" in data:
                pn = doc_number.parse(str(data["number"]))
            elif data.get("org") is not None:
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

        draft = data.get("draft") or {}
        if not isinstance(draft, dict) or (draft and not draft.get("id")):
            raise RegistryError(f"{pn}: 'draft' must be a rejected request with its id.")

        kind = _as_text(data.get("kind", KIND_CAD)) or KIND_CAD
        if kind not in ALL_KINDS:
            raise RegistryError(f"{pn}: unknown kind '{kind}'. Update Litterbox to read it.")

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

        clean_quantities = _counts(pn, data.get("quantities"), "quantities")
        clean_bom_items = _counts(pn, data.get("bom_items"), "bom_items")

        outdated = data.get("references_outdated") or []
        if not isinstance(outdated, list):
            raise RegistryError(f"{pn}: 'references_outdated' must be a list of revisions.")
        try:
            outdated = [check_revision(str(r)) for r in outdated]
        except PNError as e:
            raise RegistryError(f"{pn}: bad revision in 'references_outdated'. {e}")

        exports = data.get("exports") or {}
        if not isinstance(exports, dict) or not all(isinstance(made, dict) for made in exports.values()):
            raise RegistryError(f"{pn}: 'exports' must say which files were made for each revision.")
        try:
            exports = {check_revision(str(rev)): dict(made) for rev, made in exports.items()}
        except PNError as e:
            raise RegistryError(f"{pn}: bad revision in 'exports'. {e}")

        documents = data.get("documents") or {}
        if not isinstance(documents, dict) or not all(
                isinstance(numbers, list) and all(doc_number.try_parse(n) for n in numbers)
                for numbers in documents.values()):
            raise RegistryError(f"{pn}: 'documents' must list document numbers for each revision.")
        try:
            documents = {check_revision(str(rev)): [str(doc_number.parse(n)) for n in numbers]
                         for rev, numbers in documents.items()}
        except PNError as e:
            raise RegistryError(f"{pn}: bad revision in 'documents'. {e}")

        try:
            materials = record_materials.parse(data.get("materials"))
        except ValueError as e:
            raise RegistryError(f"{pn}: {e}")

        try:
            other_files = record_other_files.parse(data.get("other_files"))
        except ValueError as e:
            raise RegistryError(f"{pn}: {e}")

        try:
            purchasing = purchasing_info.clean(data.get("purchasing"))
        except purchasing_info.PurchasingError as e:
            raise RegistryError(f"{pn}: {e}")

        name, description = _as_text(data.get("name")), _as_text(data.get("description"))
        if "name" not in data:
            # Records made before parts had a name: the old description becomes the name.
            name, description = description, ""

        return cls(
            pn=pn,
            name=name,
            description=description,
            project=" ".join(_as_text(data.get("project")).split()),
            created_by=_as_text(data.get("created_by")),
            created_by_id=_as_text(data.get("created_by_id")),
            created_at=_as_text(data.get("created_at")),
            revision=revision,
            released_revision=released_revision,
            status=status,
            cots=bool(data.get("cots", False)),
            kind=kind,
            imported=bool(data.get("imported", False)),
            import_path=_as_text(data.get("import_path")),
            approvals=list(approvals),
            pending=pending,
            draft=draft,
            references=clean_refs,
            references_outdated=outdated,
            quantities=clean_quantities,
            bom_items=clean_bom_items,
            history=[_clean_event(e) for e in history],
            purchasing=purchasing,
            exports=exports,
            documents=documents,
            materials=materials,
            other_files=other_files,
            doc_type=_as_text(data.get("doc_type")),
            extra={k: v for k, v in data.items() if k not in _KNOWN_FIELDS},
        )


def _counts(pn, counts_by_rev, key):
    """{revision: {stem: whole number}} from a record's quantities or bom_items, checked."""
    counts_by_rev = counts_by_rev or {}
    if not isinstance(counts_by_rev, dict):
        raise RegistryError(f"{pn}: '{key}' must give how many of each part each revision uses.")
    clean = {}
    for rev, counts in counts_by_rev.items():
        try:
            rev = check_revision(str(rev))
        except PNError as e:
            raise RegistryError(f"{pn}: bad revision in '{key}'. {e}")
        if not isinstance(counts, dict) or not all(
                isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0
                for k, v in counts.items()):
            raise RegistryError(f"{pn}: '{key}' for Rev {rev} must give a whole number for each part.")
        clean[rev] = dict(counts)
    return clean


def dump(record):
    return yaml.safe_dump(
        record.to_dict(), sort_keys=False, allow_unicode=True,
        default_flow_style=False, width=100,
    )
