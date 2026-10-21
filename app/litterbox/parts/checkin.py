"""
checkin.py - Check In and Save Progress: upload a part's changes, and
(for Check In) give back its locks.

A part whose files were saved after the click is not uploaded (see util/file_snapshot.py) and stays checked out.
"""

from dataclasses import dataclass
from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError, NoChangesError
from litterbox.git import committing
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import part_changes
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.util import file_snapshot
from litterbox.vault import config


def watch_files(repo, revisions):
    """Remember the size and modified time of these parts' CAD files, as they are right now ({PN: revision}).
    Pass the result to checkin_many(snapshot=...) so a part saved after you pressed Check In is not uploaded.
    Cheap: one look at the cad folder and one metadata lookup per file; nothing is read."""
    index = record_files.cad_index(repo)
    return file_snapshot.FileSnapshot(repo, {pn: index.get(pn, {}).get(rev, []) + part_changes.gone_files(repo, pn, rev)
                                             for pn, rev in revisions.items()})


@dataclass
class CheckinResult:
    uploaded: bool              # False if there was nothing to upload
    files: list                 # the CAD files whose changes were committed this time


def _allowed(allow_unchanged, pn):
    """allow_unchanged is True/False for every part, or the set of parts that may be checked in unchanged."""
    if isinstance(allow_unchanged, bool):
        return allow_unchanged
    return pn in allow_unchanged


@diagnostics.timed("check in")
def _checkin_batch(repo, pns, comment, keep_lock, allow_unchanged, references_reader, snapshot=None):
    """Check in (or save progress on) several parts: commit each one, upload them all together, then release the
    locks. A part with a problem (not yours, nothing changed) is reported and the others carry on. If the upload
    fails, nothing is unlocked and every commit is kept so the whole thing can be tried again.

    A part whose files were saved after the click (see file_snapshot.py), or while they were being read, is
    refused and stays checked out; the others carry on."""
    repository.validate_repo(repo)
    pns = batch_core.unique_pns(pns)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "checkin")
    batch = batch_core.Batch()

    locks = lfs_locks.get_locks(repo, strict=True)
    modified = repository.get_modified(repo)
    index = record_files.cad_index(repo)
    groups, cads = {}, {}                                    # the parts to upload: pn -> every path / the CAD files
    to_commit = []                                           # (pn, message, paths) in the order checked in
    for pn in pns:
        try:
            record_path = record_store.record_relpath(pn)
            record = record_store.load(repo, pn)
            cad = index.get(pn, {}).get(record.revision, []) + part_changes.gone_files(repo, pn, record.revision)
            group = cad + [record_path]
            if not any(lfs_locks.is_mine(locks, p) for p in group):
                raise LitterboxError(f"You don't have {pn} checked out.")
            if snapshot is not None and not keep_lock and snapshot.covers(pn):
                saved = snapshot.problems(pn, cad)           # (Save Progress is meant to be used while you work)
                if saved:
                    raise LitterboxError(
                        f"{pn}: {file_snapshot.names(saved)} changed after you pressed Check In, so nothing was "
                        "uploaded for this part. It is still checked out to you. Check In again when you have "
                        "finished saving it.")

            report = part_changes.build_change_report(repo, pn, user, cad, modified)
            changed = report.changed_files
            if not report.has_changes and not _allowed(allow_unchanged, pn):
                if keep_lock:
                    diagnostics.LOG("No changes to save.")
                    batch.results[pn] = CheckinResult(False, [])
                    continue
                raise NoChangesError(pn, report.unchanged_files)

            # Commit unless the ONLY thing to do is upload commits left over from an earlier failed attempt.
            if changed or report.record_edited or not report.unpushed:
                found = None
                if references_reader is not None:
                    try:
                        found = references_reader(repo, pn, record.revision, changed)
                    except Exception as e:
                        diagnostics.LOG(f"WARNING: could not read what {pn} uses: {e}")
                record_before = (Path(repo) / record_path).read_bytes()
                record_lifecycle.record_checkin(record, user, changed, comment,
                                                references=found.references if found is not None else None,
                                                quantities=found.quantities if found is not None else None)
                record_store.save(repo, record)
                message = f"{pn}: {(comment or '').strip() or 'Update'}"
                to_commit.append((pn, message, changed, record_path, record_before))
            groups[pn], cads[pn] = group, cad
            batch.results[pn] = CheckinResult(True, changed)
        except (LitterboxError, record_model.RegistryError) as e:
            batch.errors[pn] = e

    def fail(pn, error):
        groups.pop(pn, None)
        cads.pop(pn, None)
        batch.results.pop(pn, None)
        batch.errors[pn] = error

    def saved_during(pn, saved):
        return LitterboxError(f"{pn}: {file_snapshot.names(saved)} was saved while Litterbox was reading it, so "
                              "nothing was uploaded for this part. It is still checked out to you. Check In again "
                              "when you have finished saving it.")

    def take_back(changed, record_path, record_before):
        """Unstage a part and put its record back as it was before this check-in touched it."""
        try:
            runner.run_chunked(["git", "reset", "-q"], changed + [record_path], repo)
            (Path(repo) / record_path).write_bytes(record_before)
        except (LitterboxError, OSError) as e:
            diagnostics.LOG(f"WARNING: could not fully take back the check-in of {record_path}: {e}")

    if config.get_commit_style(repo) == "per_batch" and len(to_commit) > 1:
        # One commit for the whole batch (faster). A failure here fails the batch and keeps the locks.
        before = {entry[0]: file_snapshot.stats(repo, entry[2]) for entry in to_commit}
        runner.run_chunked(["git", "add"], [path for _pn, _m, changed, record_path, _b in to_commit
                                      for path in changed + [record_path]], repo)
        survivors = []
        for entry in to_commit:
            pn, _message, changed, record_path, record_before = entry
            saved = file_snapshot.moved(repo, before[pn])
            if saved:
                take_back(changed, record_path, record_before)
                fail(pn, saved_during(pn, saved))
            else:
                survivors.append(entry)
        if survivors:
            subject, body = batch_core.batch_message([entry[1] for entry in survivors])
            committing.commit_paths(repo, subject, body, [path for _pn, _m, changed, record_path, _b in survivors
                                                 for path in changed + [record_path]])
    else:
        for pn, message, changed, record_path, record_before in to_commit:
            files = changed + [record_path]
            try:
                before = file_snapshot.stats(repo, changed)
                runner.run(["git", "add", "--"] + files, repo)
                saved = file_snapshot.moved(repo, before)
                if saved:
                    take_back(changed, record_path, record_before)
                    fail(pn, saved_during(pn, saved))
                    continue
                runner.run(["git", "commit", "-m", message, "--"] + files, repo)
            except LitterboxError as e:
                fail(pn, e)

    if not groups:
        return batch
    guarded_push.push(repo)                                   # one upload for all of them

    if keep_lock:
        # Brand-new files weren't lockable before they were uploaded. Lock them now.
        locks = lfs_locks.get_locks(repo, strict=True)
        fresh = [(f, str(pn)) for pn, cad in cads.items() for f in cad if f.lower() not in locks]
        got = lfs_locks.lock_many(repo, fresh)
        for pn, cad in cads.items():
            bad = next((got[f] for f in cad if got.get(f) is not None), None)
            if bad is not None:
                batch.errors[pn] = bad
                batch.results.pop(pn, None)
    else:
        failed = lfs_locks.unlock_mine(repo, [path for group in groups.values() for path in group])
        read_only.enforce_read_only(repo)
        if failed:
            batch.notice = lfs_locks.unlock_failure_message(failed)
    return batch


@converts_errors
def checkin(repo, pn, comment="", keep_lock=False, allow_unchanged=False, references_reader=None, snapshot=None):
    """Commit your changes, upload them, then (unless keep_lock) release the locks.

    Order matters: commit, then push, and only then unlock. If any step fails
    you keep your locks and can simply try again.
    keep_lock=True is "Save Progress".

    If nothing has changed, Check In raises NoChangesError and leaves everything
    as it was (it never turns into an undo). With allow_unchanged=True it goes
    ahead anyway: the check-in is recorded in the PN record, uploaded, and the
    locks are released. Save Progress with nothing changed just does nothing.

    references_reader(repo, pn, revision, changed_files) may return what an assembly uses and how many of
    each (a reference_reader.AssemblyRead), which is stored in the record in the same commit. It returns None
    when there is nothing to update, and any error it raises only costs the update, not the check-in.
    """
    pn = batch_core.as_pn(pn)
    try:
        return batch_core.single(_checkin_batch(repo, [pn], comment, keep_lock, allow_unchanged, references_reader, snapshot), pn)
    finally:
        if snapshot is not None:
            snapshot.release()


@converts_errors
def checkin_many(repo, pns, comment="", keep_lock=False, allow_unchanged=frozenset(), references_reader=None,
                 snapshot=None):
    """checkin() for several parts at once, with one upload for all of them. `allow_unchanged` is the set of parts
    that may be checked in even though nothing changed. `snapshot` is from watch_files(): parts saved after it was
    taken are refused (and stay checked out). Returns (done, failed) like checkout_many()."""
    pns = batch_core.unique_pns(pns)
    try:
        return batch_core.as_lists(_checkin_batch(repo, pns, comment, keep_lock, allow_unchanged, references_reader, snapshot),
                         pns)
    finally:
        if snapshot is not None:
            snapshot.release()
