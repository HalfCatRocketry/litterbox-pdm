"""
record_store.py - reading and writing records in PN-logs/, and which part numbers are taken. Documents' records
(numbered like PROP-0001, core/doc_number.py) are the same kind of record, kept in DOC-logs/: every function here
takes either number.

A record is never deleted, and a record can only be created once (create_record refuses a number that exists).
"""

import os
import tempfile
from pathlib import Path

import yaml

from litterbox import layout
from litterbox.core import doc_number
from litterbox.core.doc_number import DocNumber
from litterbox.core.numbering import next_base, next_variant
from litterbox.core.part_number import try_parse
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.util import person_name


def log_dir(repo):
    return Path(repo) / layout.LOG_DIR_NAME


def cad_dir(repo):
    return Path(repo) / layout.CAD_DIR_NAME


def cancelled_dir(repo):
    return Path(repo) / layout.CANCELLED_DIR_NAME


def doc_log_dir(repo):
    return Path(repo) / layout.DOC_LOG_DIR_NAME


def record_path(repo, pn):
    return Path(repo) / record_relpath(pn)


def record_relpath(pn):
    """Where a PN's (or a document's) record lives, relative to the repo, with forward slashes."""
    folder = layout.DOC_LOG_DIR_NAME if isinstance(pn, DocNumber) else layout.LOG_DIR_NAME
    return f"{folder}/{pn}.yaml"


def _read(path, expected_pn):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)      # safe_load only: never plain yaml.load
    except (OSError, yaml.YAMLError) as e:
        raise record_model.RegistryError(f"Could not read {path.name}: {e}")
    if not isinstance(data, dict):
        raise record_model.RegistryError(f"{path.name} is empty or not a valid record.")
    record = record_model.Record.from_dict(data)
    if record.pn != expected_pn:
        raise record_model.RegistryError(
            f"{path.name} is named {expected_pn} but its contents say {record.pn}."
        )
    return record


def load(repo, pn):
    """Load the record for a PN. Raises RegistryError if it doesn't exist."""
    path = record_path(repo, pn)
    if not path.is_file():
        raise record_model.RegistryError(f"There is no record for {pn}.")
    return _read(path, pn)


def exists(repo, pn):
    return record_path(repo, pn).is_file()


def create_record(repo, pn, name, created_by, description="", cots=False, imported=False, import_path="",
                  project="", kind=record_model.KIND_CAD, doc_type=""):
    """Create the record file for a brand-new PN and return the Record.

    The name is required. The description is optional. import_path is only kept
    for imported parts. Raises PNExistsError if that PN already has a record, so
    an existing record can never be overwritten.
    """
    name = (name or "").strip()
    description = (description or "").strip()
    created_by = person_name.PersonName((created_by or "").strip(), person_name.id_of(created_by))
    if not name:
        raise record_model.RegistryError("A name is required.")
    if not created_by:
        raise record_model.RegistryError("Could not tell who is creating this part. Set your name in git "
                            "(git config user.name).")

    record = record_model.Record(pn=pn, name=name, description=description, created_by=str(created_by),
                    created_by_id=created_by.id, created_at=record_model.now_utc(),
                    cots=bool(cots), imported=bool(imported),
                    import_path=(str(import_path).strip() if imported else ""), project=(project or "").strip(),
                    kind=kind, doc_type=doc_type)
    record_lifecycle.add_event(record, record_model.EVENT_CREATED, created_by)
    record.history[-1]["at"] = record.created_at    # created event and created_at match exactly

    path = record_path(repo, pn)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Mode "x" means "create, but fail if the file already exists".
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(record_model.dump(record))
    except FileExistsError:
        raise record_model.PNExistsError(f"{pn} already exists.")
    except OSError as e:
        raise record_model.RegistryError(f"Could not create the record for {pn}: {e}")
    return record


def save(repo, record):
    """Write changes to an existing record.

    The record file is read-only on disk unless you hold its lock, so a save
    without the lock fails here with a clear message instead of a confusing error.
    """
    path = record_path(repo, record.pn)
    if not path.is_file():
        raise record_model.RegistryError(f"There is no record for {record.pn} to save. Use create_record().")
    if not os.access(path, os.W_OK):
        raise record_model.RegistryError(
            f"The record for {record.pn} is read-only. Check the part out first so you hold its lock."
        )

    text = record_model.dump(record)
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
        raise record_model.RegistryError(f"Could not save the record for {record.pn}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


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


def list_docs(repo):
    """Every document number that has a record, sorted."""
    folder = doc_log_dir(repo)
    if not folder.is_dir():
        return []
    return sorted({number for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".yaml"
                   for number in [doc_number.try_parse(path.stem)] if number})


def used_bases(repo, org=None):
    """Set of base numbers that are taken (including void ones)."""
    return {pn.base for pn in list_pns(repo, org)}


def used_variants(repo, base, org=None):
    """Set of variant numbers that are taken for one base number."""
    return {pn.variant for pn in list_pns(repo, org) if pn.base == base}


def next_free_base(repo, org=None, start=1, allowed=None):
    """The next base number nobody has used yet, from `start` (see core/numbering.py; `allowed` leaves numbers out)."""
    return next_base(used_bases(repo, org), start, allowed)


def next_free_variant(repo, base, org=None, low=None, high=None):
    """The lowest unused variant number for a base, from `low` to `high` (`low` itself if the base is brand new)."""
    return next_variant(used_variants(repo, base, org), low, high)


def load_variants(repo, base, org=None):
    """The records of every variant of one base, in order. For the New Variant dialog."""
    return [load(repo, pn) for pn in list_pns(repo, org) if pn.base == base]
