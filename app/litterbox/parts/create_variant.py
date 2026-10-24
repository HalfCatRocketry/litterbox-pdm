"""
create_variant.py - Create Variant (Part menu): copy a part to the next free variant of its part number, as a part of
its own. For when a configuration really needs its own part number (a bracket in two lengths ordered as two items):
a different part is a different file.

The new part starts at Rev A (a new part always does), with the original's Name unless another is given, in the
original's project. Its files are copies of the original's latest revision's SolidWorks files (the model, and the
drawing pointed at the copied model, as Revise does: parts/revision_files.py), and it is checked out to you. Its
STEP and PDF are made again when it is released.

    new_pn, files = create_variant.create_variant(repo, pn)              # name and description kept
    new_pn, files = create_variant.create_variant(repo, pn, name="Bracket, long", variant=7)

The number is taken first (parts/create.py). If copying the files fails after that, the new part is left with no
files and not checked out, and the error says so: the number stays taken, like a New Part nobody has saved yet.
"""

import posixpath
from pathlib import Path

from litterbox import diagnostics
from litterbox.cad import cad_programs
from litterbox.core import configuration_names
from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.core.revision_letters import FIRST_REVISION
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import configuration_naming
from litterbox.parts import create
from litterbox.parts import permission_check
from litterbox.parts import revision_files
from litterbox.records import record_configurations
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


def copies_for(repo, record, new_pn):
    """[(old, new)]: the latest revision's SolidWorks files, under the new part's Rev A names. Its exports (STEP,
    PDF) aren't copied."""
    files = record_files.cad_files(repo, record.pn, record.revision)
    return [(rel, posixpath.join(posixpath.dirname(rel),
                                 filenames.filename(new_pn, FIRST_REVISION, file_types.extension(rel).lstrip("."))))
            for rel in files if file_types.extension(rel) in file_types.CAD_EXTENSIONS]


def kind_of(repo, record):
    """create.ASSEMBLY for a part whose model is an assembly (its variant comes from the assemblies' range), else
    create.PART."""
    files = record_files.cad_files(repo, record.pn, record.revision)
    return create.ASSEMBLY if any(file_types.is_assembly(f) for f in files) else create.PART


@converts_errors
def create_variant(repo, pn, name=None, description=None, variant=None, backend=None, log=print):
    """Copy part `pn` to a new variant of its number. Returns (new PN, [its files]); the new part is checked out to
    you. `name` and `description` default to the original's; `variant` to the next free one."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    if record.is_document:
        raise LitterboxError("Create Variant is for parts. A document can't have variants.")
    if record.uses_cad:
        if not any(file_types.extension(old) in file_types.MODEL_EXTENSIONS
                   for old, _new in copies_for(repo, record, pn)):
            raise LitterboxError(f"{pn} Rev {record.revision} has no SolidWorks part or assembly file to copy.")
        permission_check.check_solidworks_version(repo, f"copy {pn}")
    new_name = record.name if name is None or not str(name).strip() else name
    new_pn = create.new_variant(repo, pn.base, new_name, record.description if description is None else description,
                                variant=variant, org=pn.org, kind=kind_of(repo, record), noncad=not record.uses_cad)
    log(f"Created {new_pn} as a variant of {pn}")
    if not record.uses_cad:
        return new_pn, []
    try:
        return new_pn, _copy_files(repo, record, new_pn, backend, log)
    except Exception as e:
        raise LitterboxError(f"{new_pn} was created, but {pn}'s files couldn't be copied to it, so it has no files "
                             f"yet: {e}") from None


def _copy_files(repo, source, new_pn, backend, log):
    """Copy the source's files to the new part, commit them with its record, and check it out to you. A failure
    before the upload puts the record back and removes the copies; after it, only the check-out is missing."""
    user = repository.get_user(repo)
    record_path = record_store.record_relpath(new_pn)
    lfs_locks.lock(repo, record_path, new_pn)
    locked, added, pushed = [record_path], [], False
    message = f"{new_pn}: Copied from {source.pn} Rev {source.revision}"
    owns = backend is None
    try:
        with cad_programs.session():
            if owns:
                backend = cad_programs.Backends()
            files = record_files.cad_files(repo, source.pn, source.revision)
            lfs_download.download(repo, files, f"{source.pn} Rev {source.revision} to copy")
            copies = copies_for(repo, source, new_pn)
            added = [new for _old, new in copies]
            revision_files.copy_set(repo, copies, backend, log)
            record = record_store.load(repo, new_pn)
            model = next((new for new in added if file_types.extension(new) in file_types.MODEL_EXTENSIONS), None)
            before = record_configurations.named(source)
            named = configuration_naming.name_file(backend, revision_files.abs_path(repo, model), record.name,
                                                   before) if model else None
            if named or (before and before == configuration_names.clean(record.name)):
                record_configurations.set_named(record, named or before)
            record_lifecycle.add_event(record, record_model.EVENT_COPIED_FROM, user, files=added,
                                       source=f"{source.pn} Rev {source.revision}")
            record_store.save(repo, record)
            revision_files.commit_and_push(repo, message, added, [], record_path)
            pushed = True
        for rel in added:                                   # the new part is yours to work on
            lfs_locks.lock(repo, rel, new_pn)
            locked.append(rel)
    except BaseException:
        lfs_locks.force_unlock_quietly(repo, locked)
        if not pushed:
            _take_back(repo, record_path, added, message)
        read_only.enforce_read_only(repo)
        if pushed:
            raise LitterboxError(f"{new_pn} was made with its files, but it couldn't be checked out to you. Click "
                                 "Check Out to continue.") from None
        raise
    finally:
        if owns and backend is not None:
            backend.close()
    read_only.enforce_read_only(repo)
    return added


def _take_back(repo, record_path, added, message):
    """Undo an attempt that wasn't uploaded: our commit (only if it is the newest, unpushed one), the copies, and
    the record's changes."""
    try:
        ours = runner.run(["git", "log", "-1", "--format=%s"], repo, quiet=True) == message
        if ours and runner.run(["git", "rev-list", "--count", repository.UNPUSHED], repo, quiet=True) != "0":
            runner.run(["git", "reset", "-q", "--soft", "HEAD~1"], repo)
        runner.run(["git", "reset", "-q", "--", record_path, *added], repo)
        runner.run(["git", "checkout", "--", record_path], repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not fully put back {record_path}: {e}")
    for rel in added:
        try:
            (Path(repo) / rel).unlink()
        except OSError:
            pass
