"""
part_materials.py - Update Material (Part menu): read parts' materials from their files through SolidWorks and keep
them in the records (records/record_materials.py). For parts checked in without SolidWorks open, or from before
Litterbox read materials. Check-in reads them by itself when SolidWorks is open (references/reference_reader.py).

Every revision with a part file (.SLDPRT) is read, released ones too: reading changes no file. SolidWorks is used
if it's open, and otherwise started out of sight and closed afterwards. A part someone else has checked out is
skipped; one you have checked out is changed in your copy and goes up with your next Check In; the rest are each
changed under a lock and uploaded together.
"""

from litterbox.cad import file_types
from litterbox.cad.solidworks import com
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_materials
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import reference_reader

UPDATED, UNCHANGED, LOCAL = "updated", "unchanged", "updated in your copy: it goes up with your next Check In"
EVENT = "material_updated"


def part_revisions(revisions):
    """{revision: [files]} of the revisions that have a part file."""
    return {rev: files for rev, files in revisions.items()
            if any(file_types.extension(f) == file_types.PART_EXTENSION for f in files)}


def _read(repo, pn, revisions, backend):
    found = {}
    with com.com_thread():
        for revision, files in revisions.items():
            lfs_download.download(repo, files, f"files of {pn} Rev {revision}")   # SolidWorks reads the file itself
            found[revision] = reference_reader.read_part_material(repo, pn, revision, backend, files) or ""
    return found


def _apply(record, user, found):
    """Put the materials read into the record; the history says which changed. None if nothing did."""
    changed = {rev: name for rev, name in found.items() if record_materials.set_material(record, name, rev)}
    if not changed:
        return None
    return record_lifecycle.add_event(record, EVENT, user, materials=changed)


def update_materials(repo, pns, backend=None, log=print):
    """Read these parts' materials and keep them in their records. Returns {PN: UPDATED | UNCHANGED | LOCAL |
    'skipped: why'}."""
    repository.validate_repo(repo)
    user = repository.get_user(repo)
    owns, results, edits = backend is None, {}, {}
    try:
        index = record_files.cad_index(repo)
        locks = lfs_locks.get_locks(repo, strict=True)
        for pn in pns:
            pn = batch_core.as_pn(pn)
            revisions = part_revisions(index.get(pn, {}))
            if not revisions:
                results[pn] = "skipped: it has no part file (.SLDPRT)"
                continue
            lock = locks.get(record_store.record_relpath(pn).lower())
            if lock and lock[0] != "you":
                results[pn] = f"skipped: checked out by {lock[1]}"
                continue
            try:
                if backend is None:
                    backend = reference_reader.new_backend()
                found = _read(repo, pn, revisions, backend)
                record = record_store.load(repo, pn)
                if all(record_materials.is_read(record, rev) and record_materials.material(record, rev) == name
                       for rev, name in found.items()):
                    results[pn] = UNCHANGED
                elif lock:                                      # yours: in your copy, like Edit Details
                    _apply(record, user, found)
                    record_store.save(repo, record)
                    results[pn] = LOCAL
                else:
                    edits[pn] = found
            except (LitterboxError, record_model.RegistryError) as e:
                results[pn] = f"skipped: {e}"
            except Exception as e:                              # SolidWorks refused: say why, carry on
                results[pn] = f"skipped: SolidWorks couldn't read it ({e})"
            if pn in results:
                log(f"{pn}: {results[pn]}")
        if edits:                                               # one download and one upload for every record
            try:
                batch = batch_core.edit_records(repo, [
                    (pn, "checkin", lambda record, who, found=found: _apply(record, who, found),
                     f"{pn}: Material updated") for pn, found in edits.items()])
                errors, notice = batch.errors, batch.notice
            except LitterboxError as e:
                errors, notice = {pn: e for pn in edits}, ""
            if notice:
                log(notice)
            for pn in edits:
                results[pn] = f"skipped: {errors[pn]}" if pn in errors else UPDATED
                log(f"{pn}: {results[pn]}")
    finally:
        if owns and backend is not None:
            backend.close()
    return results

