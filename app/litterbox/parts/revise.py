"""
revise.py - Revise (make a new revision of a released part) and Cancel Revision.

REVISE   A released part is frozen: its files can never change. To change it, you revise it.
         Litterbox copies the model (and the drawing, pointing it at the new model) to the next
         revision letter, for example HCR-00001-001_A.SLDPRT -> HCR-00001-001_B.SLDPRT. The old
         revision is not touched, so anything that uses it keeps working. The new revision is
         in work and checked out to you.

CANCEL   Throws away a revision that is still in work (and was not the first), for example
REVISION because it was started by mistake. Nothing is deleted: its files are copied to the
         cancelled-revs folder as CANCELLED_<name> and removed from cad, so nothing can use them.
         The part goes back to its latest released revision. The cancelled letter is never reused.

Both are all-or-nothing, like an import: the new files and the record change travel in ONE commit
and ONE push. A note in .git (litterbox-revise.json) lists what an unfinished attempt has put in
the vault, so a crash or a lost race can be cleaned up exactly, without touching anything else.

Both need SolidWorks to copy the files (the same copy and re-point calls the importer uses).
"""

import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.importing import importer
from litterbox.core import filenames
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.errors import LitterboxError
from litterbox.records.error_conversion import converts_errors
from litterbox import diagnostics
from litterbox import layout
from litterbox.cad import file_types
from litterbox.cad.solidworks import com
from litterbox.util import journal as journal_file
from litterbox.parts import batch_core
from litterbox.git import lfs_locks
from litterbox.parts import permission_check
from litterbox.parts import planning
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner

JOURNAL_NAME = "litterbox-revise.json"
JOURNAL_VERSION = 1


class RevisionFailed(LitterboxError):
    """Revise or Cancel Revision could not be completed. Nothing was changed."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _abs(repo, rel):
    return str(Path(repo) / rel)


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------

def _journal_path(repo):
    return journal_file.path(repo, JOURNAL_NAME)


def _write_journal(repo, data):
    journal_file.write(repo, JOURNAL_NAME, dict(data, version=JOURNAL_VERSION))


def _clear_journal(repo):
    journal_file.clear(repo, JOURNAL_NAME)


def _read_journal(repo):
    path = _journal_path(repo)
    try:
        data = journal_file.load(repo, JOURNAL_NAME, JOURNAL_VERSION)
        if data is None:
            return None
        journal = {"op": str(data["op"]), "token": str(data["token"]), "record": str(data["record"]),
                   "added": list(data["added"]), "removed": list(data.get("removed", [])),
                   "locked": list(data.get("locked", []))}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RevisionFailed(f"The note about an unfinished revise ({path}) can't be read ({e}). "
                             "Delete it by hand if you are sure nothing is running, then try again.") from None
    folders = (f"{layout.CAD_DIR_NAME}/", f"{layout.CANCELLED_DIR_NAME}/")
    for rel in journal["added"] + journal["removed"]:
        if not str(rel).startswith(folders) or ".." in str(rel):
            raise RevisionFailed(f"The note about an unfinished revise lists a file outside the cad and "
                                 f"cancelled-revs folders ({rel}). Litterbox will not touch it. "
                                 f"Check {path} by hand.")
    if not journal["record"].startswith(f"{layout.LOG_DIR_NAME}/") or ".." in journal["record"]:
        raise RevisionFailed(f"The note about an unfinished revise lists a record outside PN-logs. Check {path}.")
    return journal


def _undo(repo, journal, log=print):
    """Put the vault back as it was before an attempt: our unpushed commit, new files, removed files, locks.
    Never deletes anything that the latest commit has. Returns 'cleaned' or 'finished'."""
    token = journal["token"]
    commit = importer._our_commit(repo, token)
    if commit:
        if importer._unpushed(repo) == 0:
            return "finished"                           # the attempt had reached the vault: keep it
        if repository.quiet_output(repo, "rev-parse", "HEAD") != commit:
            raise RevisionFailed("An unfinished revise left a commit that has not been pushed, but it is no "
                                 "longer the latest commit, so Litterbox will not undo it. Ask for help.")
        runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
    record, added, removed = journal["record"], journal["added"], journal["removed"]
    # put back anything the attempt took out of the vault, and the record
    gone = [rel for rel in removed if repository.in_head(repo, rel)]
    try:
        if gone:
            runner.run(["git", "reset", "-q", "HEAD", "--"] + gone, repo)
            runner.run(["git", "checkout", "HEAD", "--"] + gone, repo)
        runner.run(["git", "restore", "--staged", "--worktree", "--", record], repo)
    except LitterboxError as e:
        log(f"WARNING: could not fully restore the vault's files: {e}")
    # remove the new files, but only ones the vault does not own
    ours = [rel for rel in added if not repository.in_head(repo, rel)]
    if ours:
        try:
            runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--"] + ours, repo)
        except LitterboxError as e:
            log(f"WARNING: could not fully clean git's index: {e}")
    problems = []
    for rel in ours:
        path = Path(repo) / rel
        try:
            if path.exists():
                os.chmod(path, 0o644)
                path.unlink()
        except OSError as e:
            problems.append(f"{rel}: {e}")
    if problems:
        raise RevisionFailed("Some files from an unfinished revise could not be deleted (are they open in "
                             "SolidWorks?). Close them and try again:\n" + "\n".join(problems[:8]))
    try:
        (Path(repo) / layout.CANCELLED_DIR_NAME).rmdir()        # only succeeds if it is empty
    except OSError:
        pass
    lfs_locks.force_unlock_quietly(repo, journal["locked"] + [record])
    read_only.enforce_read_only(repo)
    return "cleaned"


def recover(repo, log=print):
    """Clean up after a revise or cancel that was interrupted. Returns 'nothing', 'cleaned' or 'finished'."""
    repository.validate_repo(repo)
    journal = _read_journal(repo)
    if journal is None:
        return "nothing"
    result = _undo(repo, journal, log)
    _clear_journal(repo)
    if result == "finished":
        log("The unfinished revise had actually reached the vault, so it was kept.")
    return result


# ---------------------------------------------------------------------------
# Plans (they read only)
# ---------------------------------------------------------------------------

@dataclass
class RevisePlan:
    pn: object
    name: str
    revision: str               # the revision that is being revised
    new_revision: str
    files: list                 # all files of the revision being revised
    copies: list                # [(old, new)] the SolidWorks files that will be copied
    kept: list = field(default_factory=list)       # files that stay with the old revision (exports, etc.)
    problems: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems


def _revised_name(rel, new_revision):
    file_pn, _rev, ext = filenames.parse_filename(rel)
    return f"{layout.CAD_DIR_NAME}/{filenames.filename(file_pn, new_revision, ext)}"


def _copy_list(repo, record, files):
    """([(old, new)], kept, problems) for revising the given files to the next letter."""
    new_revision = record_revisions.next_free_revision(record)
    copies, kept, problems = [], [], []
    for rel in files:
        if file_types.extension(rel) in file_types.SOLIDWORKS_EXTENSIONS:
            new = _revised_name(rel, new_revision)
            copies.append((rel, new))
            if (Path(repo) / new).exists():
                problems.append(f"{new} already exists in the cad folder.")
        else:
            kept.append(rel)
    if not any(file_types.extension(old) in file_types.MODEL_EXTENSIONS for old, _new in copies):
        problems.append("There is no SolidWorks part or assembly file to copy.")
    return copies, kept, problems


@converts_errors
def revise_plan(repo, pn, fetch=True):
    """What a revise would create, and anything that blocks it. Changes nothing."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    files, problems = planning.blockers(repo, pn, record, "revised", fetch,
                                    required=record_model.STATUS_RELEASED, required_label="released")
    if record.cots:
        problems.insert(0, record_revisions.can_revise(record))
    copies, kept, more = _copy_list(repo, record, files)
    problems += [p for p in more if p not in problems]
    return RevisePlan(pn, record.name, record.revision, record_revisions.next_free_revision(record),
                      files, copies, kept, problems)


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


def _cancelled_name(rel):
    return f"{layout.CANCELLED_DIR_NAME}/{layout.CANCELLED_PREFIX}{file_types.file_name(rel)}"


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
    moves = [(rel, _cancelled_name(rel)) for rel in files]
    for _old, new in moves:
        if (Path(repo) / new).exists():
            problems.append(f"{new} already exists.")
    return CancelPlan(pn, record.name, record.revision, record.released_revision, files, moves, problems)


# ---------------------------------------------------------------------------
# Copying with SolidWorks
# ---------------------------------------------------------------------------

def _copy_set(repo, pairs, backend, log):
    """Copy each (old, new) pair: SolidWorks files with SolidWorks, others as plain files.
    Drawings are re-pointed at the copy of the model they were drawn from."""
    new_model = {}
    for old, new in sorted(pairs, key=lambda pair: (file_types.extension(pair[0]) in file_types.DRAWING_EXTENSIONS, file_types.file_name(pair[0]).lower())):
        src, dst = _abs(repo, old), _abs(repo, new)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if file_types.extension(old) in file_types.SOLIDWORKS_EXTENSIONS:
            log(f"Copying {file_types.file_name(old)} as {file_types.file_name(new)}")
            backend.copy(src, dst)
        else:
            shutil.copyfile(src, dst)
        if not os.path.exists(dst) or (os.path.getsize(dst) == 0 and os.path.getsize(src) > 0):
            raise RevisionFailed(f"The copy {new} was not created properly.")
        if file_types.extension(old) in file_types.MODEL_EXTENSIONS:
            new_model[file_types.file_name(old).lower()] = dst
        elif file_types.extension(old) in file_types.DRAWING_EXTENSIONS:
            _repoint_drawing(dst, new_model, backend)


def _repoint_drawing(drawing, new_model, backend):
    """Make a copied drawing refer to the copied model instead of the original."""
    for stored, found in backend.references(drawing):
        target = new_model.get(file_types.file_name(stored or found).lower())
        if target is None:
            continue
        if not backend.repoint(drawing, stored, target):
            raise RevisionFailed(f"SolidWorks would not change the reference inside {file_types.file_name(drawing)}.")
    for stored, found in backend.references(drawing):
        if file_types.file_name(stored or found).lower() in new_model:
            raise RevisionFailed(f"{file_types.file_name(drawing)} still refers to the original model.")


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------

def _commit_and_push(repo, message, add, remove, record_path):
    if remove:
        for rel in remove:
            try:
                os.chmod(Path(repo) / rel, 0o644)
            except OSError:
                pass
        runner.run(["git", "rm", "-q", "-f", "--"] + remove, repo)
    runner.run(["git", "add", "--"] + add + [record_path], repo)
    runner.run(["git", "commit", "-m", message, "--"] + add + remove + [record_path], repo)
    remote.push_with_retry(repo)


@converts_errors
def revise(repo, pn, reason, backend=None, log=print):
    """Make the next revision of a released part. Call revise_plan() first and show it to the user.

    Returns the list of the new revision's files. The new revision is checked out to you.
    """
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "revise")
    reason = " ".join((reason or "").split())
    if not reason:
        raise RevisionFailed("A reason is required to revise a part.")
    recover(repo, log)
    plan = revise_plan(repo, pn)
    if not plan.ok:
        raise RevisionFailed(f"{pn} can't be revised yet:\n- " + "\n- ".join(plan.problems))

    record_path = record_store.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, new_files, journal = [], [], None
    owns_backend = backend is None
    if owns_backend:
        backend = importer.SolidWorksBackend()
    pushed = False
    try:
        with com.com_thread():
            lfs_locks.lock(repo, record_path, pn)                  # whoever gets this lock gets the revision
            locked.append(record_path)
            remote.pull(repo)                                   # lock first, THEN pull
            record = record_store.load(repo, pn)
            files = record_files.cad_files(repo, pn, record.revision)
            if record_revisions.can_revise(record) or record.revision != plan.revision:
                raise RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            copies, _kept, problems = _copy_list(repo, record, files)
            if problems:
                raise RevisionFailed("\n".join(problems))
            new_files = [new for _old, new in copies]
            journal = {"op": "revise", "token": token, "record": record_path, "added": new_files,
                       "removed": [], "locked": []}
            _write_journal(repo, journal)

            log(f"Revising {pn} from Rev {record.revision} to Rev {record_revisions.next_free_revision(record)}...")
            _copy_set(repo, copies, backend, log)
            record_revisions.mark_revised(record, user, reason, new_files)
            record_store.save(repo, record)
            message = f"{pn}: Revised to Rev {record.revision} - {reason}\n\nLitterbox-Revise: {token}"
            _commit_and_push(repo, message, new_files, [], record_path)
            pushed = True

            for rel in new_files:                             # the new revision is yours to work on
                lfs_locks.lock(repo, rel, pn)
                locked.append(rel)
    except BaseException:
        if pushed:
            # The revision exists in the vault. Do not undo it; just say what is left to do.
            lfs_locks.force_unlock_quietly(repo, locked)
            _clear_journal(repo)
            read_only.enforce_read_only(repo)
            raise RevisionFailed(f"Rev {record_store.load(repo, pn).revision} of {pn} was created, but it could not be "
                                 "checked out to you. Click Check Out to continue.") from None
        try:
            if journal is not None:
                journal["locked"] = locked
                _undo(repo, journal, log)
            else:
                lfs_locks.force_unlock_quietly(repo, locked)
        finally:
            _clear_journal(repo)
        raise
    finally:
        if owns_backend:
            backend.close()
    _clear_journal(repo)
    read_only.enforce_read_only(repo)
    return new_files


# ---------------------------------------------------------------------------
# Cancel Revision
# ---------------------------------------------------------------------------

@converts_errors
def cancel_revision(repo, pn, reason, backend=None, log=print):
    """Throw away the working revision (keeping its files in cancelled-revs). Returns the kept files.

    Call cancel_revision_plan() first and show it to the user. The part goes back to its latest
    released revision, and the cancelled letter is never used again."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "cancel_revision")
    reason = " ".join((reason or "").split())
    if not reason:
        raise RevisionFailed("A reason is required to cancel a revision.")
    recover(repo, log)
    plan = cancel_revision_plan(repo, pn)
    if not plan.ok:
        raise RevisionFailed(f"The revision of {pn} can't be cancelled yet:\n- " + "\n- ".join(plan.problems))

    record_path = record_store.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, journal = [], None
    owns_backend = backend is None
    if owns_backend:
        backend = importer.SolidWorksBackend()
    pushed = False
    kept = []
    try:
        with com.com_thread():
            lfs_locks.lock(repo, record_path, pn)
            locked.append(record_path)
            remote.pull(repo)
            record = record_store.load(repo, pn)
            if record_revisions.can_cancel_revision(record) or record.revision != plan.revision:
                raise RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            files = record_files.cad_files(repo, pn, record.revision)
            for rel in files:                                 # nobody else may pick the files up meanwhile
                lfs_locks.lock(repo, rel, pn)
                locked.append(rel)
            moves = [(rel, _cancelled_name(rel)) for rel in files]
            clashes = [new for _old, new in moves if (Path(repo) / new).exists()]
            if clashes:
                raise RevisionFailed("These already exist in cancelled-revs: " + ", ".join(clashes))
            kept = [new for _old, new in moves]
            journal = {"op": "cancel", "token": token, "record": record_path, "added": kept,
                       "removed": [old for old, _new in moves], "locked": []}
            _write_journal(repo, journal)

            log(f"Cancelling Rev {record.revision} of {pn}...")
            _copy_set(repo, moves, backend, log)
            record_revisions.mark_revision_cancelled(record, user, reason, kept)
            record_store.save(repo, record)
            message = (f"{pn}: Cancelled Rev {plan.revision} - {reason}\n\nLitterbox-Revise: {token}")
            _commit_and_push(repo, message, kept, [old for old, _new in moves], record_path)
            pushed = True
    except BaseException:
        if pushed:
            raise
        try:
            if journal is not None:
                journal["locked"] = locked
                _undo(repo, journal, log)
            else:
                lfs_locks.force_unlock_quietly(repo, locked)
        finally:
            _clear_journal(repo)
        raise
    finally:
        if owns_backend:
            backend.close()
    _clear_journal(repo)
    # the cancelled files are gone from cad, so their locks (and the record's) can go
    lfs_locks.force_unlock_quietly(repo, [rel for rel in locked if rel != record_path])
    failed = lfs_locks.unlock_mine(repo, [record_path])
    read_only.enforce_read_only(repo)
    if failed:
        raise RevisionFailed(lfs_locks.unlock_failure_message(failed))
    return kept
