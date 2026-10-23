"""
cancel_revision.py - Cancel Revision: throw away a revision that was never released. Its files are kept
in cancelled-revs/ as CANCELLED_..., and its letter is never used again.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_backend
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.parts import revision_files
from litterbox.records import record_files
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


@dataclass
class CancelPlan:
    pn: object
    name: str
    revision: str               # the revision that would be cancelled
    back_to: str                # the revision the part returns to
    files: list                 # the files of the revision that would be cancelled
    moves: list                 # [(old, new)] where they would be kept
    problems: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems


@converts_errors
def cancel_revision_plan(repo, pn, fetch=True):
    """What Cancel Revision would move, and anything that blocks it. Changes nothing."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    files = record_files.cad_files(repo, pn, record.revision)
    problems = []
    problem = record_revisions.can_cancel_revision(record)
    if problem:
        problems.append(problem)
    if fetch:
        try:
            runner.run(["git", "fetch"], repo, quiet=True)
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not check the vault for newer changes. {e}")
    locks = lfs_locks.get_locks(repo, strict=True)
    group = files + [record_store.record_relpath(pn)]
    others = sorted({locks[p.lower()][1] for p in group if p.lower() in locks and locks[p.lower()][0] != "you"})
    if others:
        problems.append("It is checked out by " + ", ".join(others) + ".")
    moves = [(rel, revision_files.cancelled_name(rel)) for rel in files]
    for _old, new in moves:
        if (Path(repo) / new).exists():
            problems.append(f"{new} already exists.")
    return CancelPlan(pn, record.name, record.revision, record.released_revision, files, moves, problems)


@converts_errors
def cancel_revision(repo, pn, reason, backend=None, log=print):
    """Throw away the working revision (keeping its files in cancelled-revs). Returns the kept files.

    Call cancel_revision_plan() first and show it to the user. The part goes back to its latest
    released revision, and the cancelled letter is never used again."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "cancel_revision")
    permission_check.check_parts(repo, [pn], "cancel_revision")
    reason = " ".join((reason or "").split())
    if not reason:
        raise revision_files.RevisionFailed("A reason is required to cancel a revision.")
    revision_files.recover(repo, log)
    plan = cancel_revision_plan(repo, pn)
    if not plan.ok:
        raise revision_files.RevisionFailed(f"The revision of {pn} can't be cancelled yet:\n- " + "\n- ".join(plan.problems))

    record_path = record_store.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, journal = [], None
    owns_backend = backend is None
    if owns_backend:
        backend = sw_backend.SolidWorksBackend()
    pushed = False
    kept = []
    try:
        with com.com_thread():
            lfs_locks.lock(repo, record_path, pn)
            locked.append(record_path)
            remote.pull(repo)
            record = record_store.load(repo, pn)
            if record_revisions.can_cancel_revision(record) or record.revision != plan.revision:
                raise revision_files.RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            files = record_files.cad_files(repo, pn, record.revision)
            for rel in files:                                 # nobody else may pick the files up meanwhile
                lfs_locks.lock(repo, rel, pn)
                locked.append(rel)
            lfs_download.download(repo, files, f"{pn} Rev {record.revision} to keep")     # SolidWorks copies the real files
            moves = [(rel, revision_files.cancelled_name(rel)) for rel in files]
            clashes = [new for _old, new in moves if (Path(repo) / new).exists()]
            if clashes:
                raise revision_files.RevisionFailed("These already exist in cancelled-revs: " + ", ".join(clashes))
            kept = [new for _old, new in moves]
            journal = {"op": "cancel", "token": token, "record": record_path, "added": kept,
                       "removed": [old for old, _new in moves], "locked": []}
            revision_files.write_journal(repo, journal)

            log(f"Cancelling Rev {record.revision} of {pn}...")
            revision_files.copy_set(repo, moves, backend, log)
            record_revisions.mark_revision_cancelled(record, user, reason, kept)
            record_store.save(repo, record)
            message = (f"{pn}: Cancelled Rev {plan.revision} - {reason}\n\nLitterbox-Revise: {token}")
            revision_files.commit_and_push(repo, message, kept, [old for old, _new in moves], record_path)
            pushed = True
    except BaseException:
        if pushed:
            raise
        try:
            if journal is not None:
                journal["locked"] = locked
                revision_files.undo_attempt(repo, journal, log)
            else:
                lfs_locks.force_unlock_quietly(repo, locked)
        finally:
            revision_files.clear_journal(repo)
        raise
    finally:
        if owns_backend:
            backend.close()
    revision_files.clear_journal(repo)
    # the cancelled files are gone from cad, so their locks (and the record's) can go
    lfs_locks.force_unlock_quietly(repo, [rel for rel in locked if rel != record_path])
    failed = lfs_locks.unlock_mine(repo, [record_path])
    read_only.enforce_read_only(repo)
    if failed:
        raise revision_files.RevisionFailed(lfs_locks.unlock_failure_message(failed))
    return kept
