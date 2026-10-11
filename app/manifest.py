r"""
manifest.py - the import manifest: a YAML file that says what an import will do.

The importer works in three phases:

    1. SCAN     scan.py walks your old CAD folders (read-only) and writes a manifest.
    2. REVIEW   you edit the manifest: fix names, untick things.
    3. EXECUTE  Litterbox gives each included item a part number and brings it in.

The manifest is plain YAML so it can be read and edited by hand:

    manifest_version: 1
    created_at: '2026-10-08T20:00:00Z'
    sources:
    - D:\Old CAD
    stats: {...}                   totals worked out by the scan (information only)
    items:
    - id: 7
      include: true                set to false to leave this out of the import
      name: valve body             required for included items; becomes the part's Name
      description: valve_body.SLDPRT, valve_body.SLDDRW     the old file names
      cots: false                  true for purchased parts
      kind: part                   part, assembly or drawing (a drawing with no model found)
      files:                       what is brought in under ONE new part number
      - path: D:\Old CAD\valves\valve_body.SLDPRT      (the first file is the model)
        type: SLDPRT
        size: 182272
        sha256: 9f2c...
      warnings:                    things the scan noticed; delete the lines you have dealt with
      - In a folder named 'Old'.
      identical_to: [12, 31]       other items whose model file is byte-for-byte the same (information only)
      already_imported_as: HCR-10001-001     set when this exact file was imported before
      pn: HCR-10002-001            filled in when the item has been imported

Nothing in here is ever deduplicated for you: every included item gets its own
part number. identical_to is there so that YOU can see which ones are copies of
each other and replace them by hand later.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

import create

VERSION = 1
KINDS = ("part", "assembly", "drawing")

HEADER = """\
# Litterbox import manifest.
#
# This file lists what an import would bring in. Nothing has been changed on your
# computer or in the vault by creating it. Edit it freely, then run the import.
#
#   include: false    leaves an item out of the import
#   name:             required for every included item (it becomes the part's Name)
#   cots:             always false from a scan. Purchased parts are brought in with Import COTS.
#   warnings:         things the scan noticed; they are only notes, delete them as you go
#   identical_to:     other items whose main file is identical (information only)
#   pn:               filled in by the import. Items that have a pn are skipped if you run it again.
#
"""


class ManifestError(Exception):
    """The manifest file is damaged or has a mistake in it. The message is safe to show to a user."""


@dataclass
class FileEntry:
    path: str
    type: str = ""          # SLDPRT, SLDASM, SLDDRW
    size: int = 0
    sha256: str = ""


@dataclass
class Item:
    id: int
    name: str
    description: str = ""
    kind: str = "part"
    include: bool = True
    cots: bool = False
    files: list = field(default_factory=list)          # FileEntry; the first one is the model
    warnings: list = field(default_factory=list)
    identical_to: list = field(default_factory=list)
    already_imported_as: str = ""
    pn: str = ""

    @property
    def main_path(self):
        return self.files[0].path if self.files else ""

    def to_dict(self):
        data = {
            "id": self.id,
            "include": self.include,
            "name": self.name,
            "description": self.description,
            "cots": self.cots,
            "kind": self.kind,
        }
        if self.pn:
            data["pn"] = self.pn
        data["files"] = [{"path": f.path, "type": f.type, "size": f.size, "sha256": f.sha256} for f in self.files]
        if self.warnings:
            data["warnings"] = list(self.warnings)
        if self.identical_to:
            data["identical_to"] = list(self.identical_to)
        if self.already_imported_as:
            data["already_imported_as"] = self.already_imported_as
        return data


@dataclass
class Manifest:
    sources: list
    items: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    created_at: str = ""
    version: int = VERSION

    def to_dict(self):
        return {
            "manifest_version": self.version,
            "created_at": self.created_at,
            "sources": list(self.sources),
            "stats": self.stats,
            "items": [item.to_dict() for item in self.items],
        }


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Saving and loading
# ---------------------------------------------------------------------------

def save(manifest, path):
    """Write the manifest to `path` (a temporary file first, so a crash can't leave half a manifest)."""
    path = Path(path)
    text = HEADER + yaml.safe_dump(manifest.to_dict(), sort_keys=False, allow_unicode=True,
                                   default_flow_style=False, width=100000)
    tmp = path.with_name(f".tmp-{path.name}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        tmp.replace(path)
    except OSError as e:
        raise ManifestError(f"Could not write the manifest {path}: {e}")


def _bool(value, where, key):
    if not isinstance(value, bool):
        raise ManifestError(f"{where}: '{key}' must be true or false (it is {value!r}).")
    return value


def _text(value):
    return "" if value is None else str(value).strip()


def load(path):
    """Read and check a manifest. Raises ManifestError, with a message that says where the problem is."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except OSError as e:
        raise ManifestError(f"Could not read the manifest {path}: {e}")
    except yaml.YAMLError as e:
        raise ManifestError(f"The manifest {path.name} is not valid YAML. The problem is near:\n{e}")
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name} is empty or is not a Litterbox manifest.")
    if data.get("manifest_version") != VERSION:
        raise ManifestError(f"{path.name} has manifest_version {data.get('manifest_version')!r}; "
                            f"this version of Litterbox reads version {VERSION}.")
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ManifestError("The manifest has no 'items' list.")

    items, seen = [], set()
    for position, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise ManifestError(f"Item number {position} in the list is not a set of fields.")
        item_id = raw.get("id")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise ManifestError(f"Item number {position} in the list has no whole-number 'id'.")
        if item_id in seen:
            raise ManifestError(f"Two items have the id {item_id}. Every id must be different.")
        seen.add(item_id)
        where = f"Item {item_id}"
        kind = _text(raw.get("kind")) or "part"
        if kind not in KINDS:
            raise ManifestError(f"{where}: 'kind' must be one of {', '.join(KINDS)} (it is {kind!r}).")
        files_raw = raw.get("files")
        if not isinstance(files_raw, list) or not files_raw:
            raise ManifestError(f"{where}: it needs a 'files' list with at least one file.")
        files = []
        for entry in files_raw:
            if not isinstance(entry, dict) or not _text(entry.get("path")):
                raise ManifestError(f"{where}: every file needs a 'path'.")
            size = entry.get("size", 0)
            if isinstance(size, bool) or not isinstance(size, int):
                raise ManifestError(f"{where}: the file size of {entry['path']} must be a whole number.")
            files.append(FileEntry(_text(entry["path"]), _text(entry.get("type")), size, _text(entry.get("sha256"))))
        for key in ("warnings", "identical_to"):
            if raw.get(key) is not None and not isinstance(raw.get(key), list):
                raise ManifestError(f"{where}: '{key}' must be a list.")
        items.append(Item(
            id=item_id,
            name=_text(raw.get("name")),
            description=_text(raw.get("description")),
            kind=kind,
            include=_bool(raw.get("include", True), where, "include"),
            cots=_bool(raw.get("cots", False), where, "cots"),
            files=files,
            warnings=[str(w) for w in raw.get("warnings") or []],
            identical_to=list(raw.get("identical_to") or []),
            already_imported_as=_text(raw.get("already_imported_as")),
            pn=_text(raw.get("pn")),
        ))

    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    return Manifest(sources=[str(s) for s in data.get("sources") or []], items=items, stats=stats,
                    created_at=_text(data.get("created_at")), version=VERSION)


# ---------------------------------------------------------------------------
# Using a manifest
# ---------------------------------------------------------------------------

def pending_items(manifest):
    """The items an import would act on: included, and not already given a part number."""
    return [item for item in manifest.items if item.include and not item.pn]


def problems(manifest):
    """Mistakes that would stop an import, as a list of messages (empty if it is ready to go)."""
    found = []
    for item in pending_items(manifest):
        if not item.name:
            found.append(f"Item {item.id} ({item.main_path}) has no name.")
        elif len(item.name) > create.MAX_NAME:
            found.append(f"Item {item.id}: the name is longer than {create.MAX_NAME} characters.")
        if len(item.description) > create.MAX_DESCRIPTION:
            found.append(f"Item {item.id}: the description is longer than {create.MAX_DESCRIPTION} characters.")
    return found


def specs(manifest):
    """(items, PartSpecs) for create.create_many, in the same order. Imported parts get their old path recorded."""
    chosen = pending_items(manifest)
    return chosen, [
        create.PartSpec(name=item.name, description=item.description, cots=item.cots,
                        imported=True, import_path=item.main_path)
        for item in chosen
    ]


def record_assignments(manifest, items, pns):
    """Write the new part numbers into the manifest (so a second run skips these items)."""
    for item, pn in zip(items, pns):
        item.pn = str(pn)