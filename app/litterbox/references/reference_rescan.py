"""
reference_rescan.py - reading every assembly's references, counting its parts, and finding its Toolbox parts and
files from outside the vault (records/record_other_files.py), again from its files and saving them in the records (for vaults whose records predate reference tracking, after a check-in without
SolidWorks, or after a fix by hand).
"""


from litterbox import diagnostics
from litterbox.core import file_types
from litterbox.cad import cad_programs
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_other_files
from litterbox.records import record_store
from litterbox.references import reference_model
from litterbox.references import reference_reader


def rescan(repo, pns=None, backend=None, log=print):
    """Read the references of assemblies straight from their files, count their parts, and store both in the
    records.

    Used by "Update references", "Update BOM" and after an import. Covers every revision whose files are on disk.
    Each record is changed under its own lock and uploaded. A part that anyone has checked out, or
    whose files have not been downloaded, is skipped (the reason is in the result).
    Returns {PN: 'updated' | 'unchanged' | 'skipped: why'}; an assembly whose references were saved but whose
    parts could not be counted gives 'updated, but ...: why'.
    """
    repository.validate_repo(repo)
    owns = backend is None
    results, edits = {}, {}
    try:
        index = record_files.cad_index(repo)
        locks = lfs_locks.get_locks(repo, strict=True)
        for pn in (pns or record_store.list_pns(repo)):
            pn = batch_core.as_pn(pn)
            revisions = index.get(pn, {})
            if not any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS for fs in revisions.values() for f in fs):
                continue
            lock = locks.get(record_store.record_relpath(pn).lower())
            if lock:
                results[pn] = f"skipped: checked out by {'you' if lock[0] == 'you' else lock[1]}. Check it in first."
                log(f"{pn}: {results[pn]}")
                continue
            try:
                if backend is None:
                    backend = reference_reader.new_backend()
                outcome = _rescan_one(repo, pn, revisions, backend, index)
            except LitterboxError as e:
                outcome = f"skipped: {e}"
            except Exception as e:
                outcome = f"skipped: {e}"
            if isinstance(outcome, tuple):
                edits[pn] = outcome[1:]                    # saved all together below
            else:
                results[pn] = outcome
                log(f"{pn}: {results[pn]}")
        if edits:                                           # one download and one upload for every record
            try:
                batch = batch_core.edit_records(repo, [(pn, "checkin", edit, f"{pn}: Updated list of parts used")
                                                 for pn, (edit, _problem) in edits.items()])
                errors, notice = batch.errors, batch.notice
            except LitterboxError as e:
                errors, notice = dict.fromkeys(edits, e), ""
            if notice:
                log(notice)
            for pn, (_edit, problem) in edits.items():
                results[pn] = f"skipped: {errors[pn]}" if pn in errors else (
                    f"updated, but its parts could not be counted: {problem}" if problem else "updated")
                log(f"{pn}: {results[pn]}")
    finally:
        if owns and backend is not None:
            backend.close()
    return results


def _download_used(repo, index, stems):
    """Download the models an assembly uses, so SolidWorks can load them: a component it can't find is
    suppressed, and would not be counted."""
    wanted = []
    for stem in stems:
        parts = reference_model.split_stem(stem)
        if parts is not None:
            wanted += [f for f in index.get(parts[0], {}).get(parts[1], [])
                       if file_types.extension(f) in file_types.MODEL_EXTENSIONS]
    lfs_download.download(repo, wanted, "parts the assembly uses")


def _rescan_one(repo, pn, revisions, backend, index=None):
    found, counted, other, problems = {}, {}, {}, []
    with cad_programs.session():
        for revision, files in revisions.items():
            if not any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS for f in files):
                continue
            lfs_download.download(repo, files, f"files of {pn} Rev {revision}")    # SolidWorks reads the file itself
            found[revision] = reference_reader.read_assembly_references(repo, pn, revision, backend, files)
            try:
                _download_used(repo, index or {}, found[revision])
                lfs_download.download(repo, reference_reader.vault_files_used(repo, pn, revision, backend, files),
                                      "Toolbox parts the assembly uses")
                counted[revision] = reference_reader.read_assembly_quantities(repo, pn, revision, backend, files,
                                                                              found[revision])
            except Exception as e:
                problems.append(f"Rev {revision}: {e}" if len(revisions) > 1 else str(e))
            try:
                other[revision] = reference_reader.read_other_files(repo, pn, revision, backend, files)
            except Exception as e:                      # left unread: Release under a Toolbox rule asks again
                diagnostics.LOG(f"WARNING: could not tell whether {pn} Rev {revision} uses Toolbox parts or files "
                                f"from outside the vault: {e}")
    problem = " ".join(problems)
    current = record_store.load(repo, pn)
    if all(current.references.get(rev) == sorted(set(stems), key=str.lower)
           and rev not in current.references_outdated
           and (rev not in counted or current.quantities.get(rev) == counted[rev])
           and (rev not in other or current.other_files.get(rev) == other[rev]) for rev, stems in found.items()):
        if problem:
            return f"skipped: its parts could not be counted. {problem}"
        return "unchanged"
    changed = []

    def edit(record, user):
        for revision, stems in found.items():
            moved = record_lifecycle.set_references(record, stems, revision)
            if revision in counted:
                moved = record_lifecycle.set_quantities(record, counted[revision], revision) or moved
            if revision in other:
                moved = record_other_files.set_other_files(record, other[revision], revision) or moved
            if moved:
                changed.append(revision)
        return record_lifecycle.add_event(record, "references_updated", user,
                                  references={rev: record.references.get(rev, []) for rev in changed},
                                  quantities={rev: record.quantities[rev] for rev in changed
                                              if rev in record.quantities} or None)

    return "edit", edit, problem
