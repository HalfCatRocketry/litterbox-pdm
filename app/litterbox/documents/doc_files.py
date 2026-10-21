"""
doc_files.py - a document's files: Add Files... copies files in under the document's name for its working revision
(PROP-0001_A.docx, PROP-0001_A.pdf in the documents folder), and Remove File takes one out. You must have the
document checked out; Check In uploads the change and Undo Checkout throws it away, as for a part's files.

A revision has at most one file of each type (by extension, ignoring capitals): adding a second .docx replaces the
first when asked to. Any type of file may be added.
"""

import os
import shutil
import stat
from pathlib import Path

from litterbox import layout
from litterbox.core import doc_number
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


def _checked_out(repo, number):
    """The document's record, if you have it checked out and its working revision is in work."""
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "edit_details")
    if not lfs_locks.is_mine(lfs_locks.get_locks(repo, strict=True), record_store.record_relpath(number)):
        raise LitterboxError(f"You don't have {number} checked out. Check it out to change its files.")
    record = record_store.load(repo, number)
    if record.status != record_model.STATUS_IN_WORK:
        raise LitterboxError(f"{number} is {record.status}, so its files can't change.")
    return record


def target_of(number, revision, source):
    """The vault path a file is added under: documents/PROP-0001_A.docx for C:/work/plan.docx."""
    extension = Path(str(source)).suffix.lstrip(".")
    if not extension:
        raise LitterboxError(f"{Path(str(source)).name} has no file type (like .docx or .pdf), so it can't be named.")
    return f"{layout.DOC_DIR_NAME}/{doc_number.filename(number, revision, extension)}"


def clashes(repo, number, sources):
    """The files the revision already has that adding `sources` would replace (same type), as vault paths."""
    record = record_store.load(repo, number)
    have = {Path(rel).suffix.lower(): rel for rel in record_files.cad_files(repo, number, record.revision)}
    return [have[Path(str(src)).suffix.lower()] for src in sources if Path(str(src)).suffix.lower() in have]


@converts_errors
def add_files(repo, number, sources, replace=False):
    """Copy files into the document's working revision. Refuses to replace a file of the same type unless
    `replace`. Returns the vault paths added."""
    repository.validate_repo(repo)
    number = batch_core.as_pn(number)
    record = _checked_out(repo, number)
    sources = [Path(str(src)) for src in sources]
    if not sources:
        raise LitterboxError("Choose at least one file to add.")
    kinds = [src.suffix.lower() for src in sources]
    if len(set(kinds)) != len(kinds):
        raise LitterboxError("Add one file of each type: a revision keeps one .docx, one .pdf and so on.")
    for src in sources:
        if not src.is_file():
            raise LitterboxError(f"{src} isn't a file that can be read.")
    if Path(repo).resolve() in [parent for src in sources for parent in src.resolve().parents]:
        raise LitterboxError("Add files from outside the vault folder.")
    replaced = clashes(repo, number, sources)
    if replaced and not replace:
        raise LitterboxError(f"Rev {record.revision} already has {', '.join(Path(r).name for r in replaced)}.")
    added = []
    for src in sources:
        old = next((r for r in replaced if Path(r).suffix.lower() == src.suffix.lower()), None)
        rel = old or target_of(number, record.revision, src)
        target = Path(repo) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            os.chmod(target, stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
        shutil.copyfile(src, target)
        added.append(rel)
    return added


@converts_errors
def remove_file(repo, number, rel):
    """Take one file out of the document's working revision (Check In uploads the removal)."""
    repository.validate_repo(repo)
    number = batch_core.as_pn(number)
    record = _checked_out(repo, number)
    if rel not in record_files.cad_files(repo, number, record.revision):
        raise LitterboxError(f"{rel} isn't a file of {number} Rev {record.revision}.")
    target = Path(repo) / rel
    os.chmod(target, stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
    target.unlink()
