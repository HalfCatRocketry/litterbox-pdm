"""
doc_types.py - the org's document types (.litterbox/document_types.yaml): each has a fixed key, a name and the
prefix its numbers take (Propulsion Document, PROP: PROP-0001, PROP-0002, ...). Admins and the Owner set them up
(Team > Document Types...), changed under a lock with a pull before and a push after, like the workflows.

    document_types:
      prop: {name: Propulsion Document, prefix: PROP}
      test: {name: Test Procedure, prefix: TP, hidden: true}

The key never changes, so renaming a type or changing its prefix never breaks the documents already made (they
keep their numbers). A type that documents use can be hidden (New Document stops offering it) but never removed.
Saving the first types makes the vault need this Litterbox or newer, since older ones don't know documents.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from litterbox import layout
from litterbox.core import doc_number
from litterbox.core.part_number import PNError
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_permissions
from litterbox.util import fast_yaml
from litterbox.vault import config_write
from litterbox.vault import shared_files


MIN_VERSION = "0.5.1"           # the first Litterbox that knows documents
MAX_NAME = 60


class DocTypeError(LitterboxError):
    """A document type is wrong, or can't be changed that way. The message is safe to show."""


@dataclass
class DocType:
    key: str
    name: str
    prefix: str
    hidden: bool = False
    extra: dict = field(default_factory=dict)       # fields a newer Litterbox wrote, kept so nothing is lost

    def to_dict(self):
        data = {"name": self.name, "prefix": self.prefix}
        if self.hidden:
            data["hidden"] = True
        data.update({k: v for k, v in self.extra.items() if k not in data})
        return data

    def label(self):
        return f"{self.name} ({self.prefix})"


def make_key(name, taken):
    """A key for a new type from its name: 'Propulsion Document' -> 'propulsion_document', made unique."""
    base = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "type"
    key, number = base, 2
    while key in taken:
        key, number = f"{base}_{number}", number + 1
    return key


def validate(types):
    """Raise DocTypeError unless the types are usable: names and prefixes given, prefixes valid and different."""
    keys, prefixes = set(), {}
    for t in types:
        if not t.key or t.key in keys:
            raise DocTypeError(f"Two document types share the key '{t.key}'.")
        keys.add(t.key)
        t.name = " ".join(str(t.name or "").split())
        if not t.name:
            raise DocTypeError("Every document type needs a name.")
        if len(t.name) > MAX_NAME:
            raise DocTypeError(f"Keep a document type's name under {MAX_NAME} characters.")
        try:
            t.prefix = doc_number.check_prefix(t.prefix)
        except PNError as e:
            raise DocTypeError(str(e)) from None
        if t.prefix in prefixes:
            raise DocTypeError(f"{t.name} and {prefixes[t.prefix]} both use the prefix {t.prefix}.")
        prefixes[t.prefix] = t.name


def load(repo):
    """The org's document types, in the file's order. No file means none."""
    path = Path(repo) / layout.DOC_TYPES_FILE
    if not path.is_file():
        return []
    try:
        data = fast_yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise DocTypeError(f"Could not read {layout.DOC_TYPES_FILE}: {e}") from None
    body = data.get("document_types") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        return []
    types = []
    for key, item in body.items():
        if not isinstance(item, dict):
            raise DocTypeError(f"The document type '{key}' in {layout.DOC_TYPES_FILE} should have a name and prefix.")
        types.append(DocType(str(key), str(item.get("name") or ""), str(item.get("prefix") or ""),
                             bool(item.get("hidden", False)),
                             {k: v for k, v in item.items() if k not in ("name", "prefix", "hidden")}))
    validate(types)
    return types


def save(repo, types):
    path = Path(repo) / layout.DOC_TYPES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp-document_types.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump({"document_types": {t.key: t.to_dict() for t in types}}, f, sort_keys=False,
                       allow_unicode=True)
    tmp.replace(path)


def by_key(types):
    return {t.key: t for t in types}


def in_use(repo):
    """{type key: how many documents} for the types documents use."""
    counts = {}
    for number in record_store.list_docs(repo):
        try:
            key = record_store.load(repo, number).doc_type
        except record_model.RegistryError:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def check_kept(before, after, used):
    """Refuse removing a type that documents use (hide it instead)."""
    kept = {t.key for t in after}
    for t in before:
        if t.key not in kept and used.get(t.key):
            raise DocTypeError(f"{t.name} is used by {used[t.key]} document{'s' if used[t.key] != 1 else ''}, so it "
                               "can't be removed. Hide it instead.")


@converts_errors
def edit_types(repo, change, message):
    """Change the document types for everyone: lock the file, get the latest, `change(types)` (a list to change in
    place), check, commit, push, unlock. If anything fails it is put back. Admins and the Owner only."""
    repository.validate_repo(repo)
    team_permissions.require(repo, "manage_doc_types")

    def make_change():
        before = load(repo)
        types = [DocType(t.key, t.name, t.prefix, t.hidden, dict(t.extra)) for t in before]
        result = change(types)
        validate(types)
        check_kept(before, types, in_use(repo))
        save(repo, types)
        config_write.stamp(repo, min_version=MIN_VERSION)
        return [layout.DOC_TYPES_FILE, layout.CONFIG_PATH], message, result
    return shared_files.edit(repo, [layout.DOC_TYPES_FILE, layout.CONFIG_PATH], "the document types file",
                             make_change)
