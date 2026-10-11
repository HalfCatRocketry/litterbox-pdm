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

import contextlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import importer
import litterbox_engine as eng
import pn as pn_module
import registry

JOURNAL_NAME = "litterbox-revise.json"
JOURNAL_VERSION = 1
MODEL_EXTENSIONS = (".sldprt", ".sldasm")
DRAWING_EXTENSIONS = (".slddrw",)
SOLIDWORKS_EXTENSIONS = MODEL_EXTENSIONS + DRAWING_EXTENSIONS


class RevisionFailed(eng.LitterboxError):
    """Revise or Cancel Revision could not be completed. Nothing was changed."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _ext(path):
    return PurePosixPath(str(path).replace("\\", "/")).suffix.lower()


def _name(path):
    return PurePosixPath(str(path).replace("\\", "/")).name


def _abs(repo, rel):
    return str(Path(repo) / rel)


@contextlib.contextmanager
def _com_thread():
    """SolidWorks is reached through COM, which must be switched on in the thread that uses it."""
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:                                   # not Windows, or no pywin32 (tests)
        pythoncom = None
    try:
        yield
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------

def _journal_path(repo):
    return Path(repo) / ".git" / JOURNAL_NAME


def _write_journal(repo, data):
    data = dict(data, version=JOURNAL_VERSION)
    path = _journal_path(repo)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


def _clear_journal(repo):
    try:
        _journal_path(repo).unlink()
    except FileNotFoundError:
        pass


def _read_journal(repo):
    path = _journal_path(repo)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != JOURNAL_VERSION:
            raise ValueError("unknown version")
        journal = {"op": str(data["op"]), "token": str(data["token"]), "record": str(data["record"]),
                   "added": list(data["added"]), "removed": list(data.get("removed", [])),
                   "locked": list(data.get("locked", []))}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RevisionFailed(f"The note about an unfinished revise ({path}) can't be read ({e}). "
                             "Delete it by hand if you are sure nothing is running, then try again.") from None
    folders = (f"{registry.CAD_DIR_NAME}/", f"{registry.CANCELLED_DIR_NAME}/")
    for rel in journal["added"] + journal["removed"]:
        if not str(rel).startswith(folders) or ".." in str(rel):
            raise RevisionFailed(f"The note about an unfinished revise lists a file outside the cad and "
                                 f"cancelled-revs folders ({rel}). Litterbox will not touch it. "
                                 f"Check {path} by hand.")
    if not journal["record"].startswith(f"{registry.LOG_DIR_NAME}/") or ".." in journal["record"]:
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
        if importer._git_out(repo, "rev-parse", "HEAD") != commit:
            raise RevisionFailed("An unfinished revise left a commit that has not been pushed, but it is no "
                                 "longer the latest commit, so Litterbox will not undo it. Ask for help.")
        eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
    record, added, removed = journal["record"], journal["added"], journal["removed"]
    # put back anything the attempt took out of the vault, and the record
    gone = [rel for rel in removed if importer._tracked(repo, rel)]
    try:
        if gone:
            eng.run(["git", "reset", "-q", "HEAD", "--"] + gone, repo)
            eng.run(["git", "checkout", "HEAD", "--"] + gone, repo)
        eng.run(["git", "restore", "--staged", "--worktree", "--", record], repo)
    except eng.LitterboxError as e:
        log(f"WARNING: could not fully restore the vault's files: {e}")
    # remove the new files, but only ones the vault does not own
    ours = [rel for rel in added if not importer._tracked(repo, rel)]
    if ours:
        try:
            eng.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--"] + ours, repo)
        except eng.LitterboxError as e:
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
        (Path(repo) / registry.CANCELLED_DIR_NAME).rmdir()        # only succeeds if it is empty
    except OSError:
        pass
    eng._force_unlock_quietly(repo, journal["locked"] + [record])
    eng.enforce_read_only(repo)
    return "cleaned"


def recover(repo, log=print):
    """Clean up after a revise or cancel that was interrupted. Returns 'nothing', 'cleaned' or 'finished'."""
    eng.validate_repo(repo)
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
    file_pn, _rev, ext = pn_module.parse_filename(rel)
    return f"{registry.CAD_DIR_NAME}/{pn_module.filename(file_pn, new_revision, ext)}"


def _copy_list(repo, record, files):
    """([(old, new)], kept, problems) for revising the given files to the next letter."""
    new_revision = registry.next_free_revision(record)
    copies, kept, problems = [], [], []
    for rel in files:
        if _ext(rel) in SOLIDWORKS_EXTENSIONS:
            new = _revised_name(rel, new_revision)
            copies.append((rel, new))
            if (Path(repo) / new).exists():
                problems.append(f"{new} already exists in the cad folder.")
        else:
            kept.append(rel)
    if not any(_ext(old) in MODEL_EXTENSIONS for old, _new in copies):
        problems.append("There is no SolidWorks part or assembly file to copy.")
    return copies, kept, problems


@eng._converts_errors
def revise_plan(repo, pn, fetch=True):
    """What a revise would create, and anything that blocks it. Changes nothing."""
    eng.validate_repo(repo)
    pn = eng._as_pn(pn)
    record = registry.load(repo, pn)
    files, problems = eng._blockers(repo, pn, record, "revised", fetch,
                                    required=registry.STATUS_RELEASED, required_label="released")
    if record.cots:
        problems.insert(0, registry.can_revise(record))
    copies, kept, more = _copy_list(repo, record, files)
    problems += [p for p in more if p not in problems]
    return RevisePlan(pn, record.name, record.revision, registry.next_free_revision(record),
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
    return f"{registry.CANCELLED_DIR_NAME}/{registry.CANCELLED_PREFIX}{_name(rel)}"


@eng._converts_errors
def cancel_revision_plan(repo, pn, fetch=True):
    """What Cancel Revision would move, and anything that blocks it. Changes nothing."""
    eng.validate_repo(repo)
    pn = eng._as_pn(pn)
    record = registry.load(repo, pn)
    files = registry.cad_files(repo, pn, record.revision)
    problems = []
    problem = registry.can_cancel_revision(record)
    if problem:
        problems.append(problem)
    if fetch:
        try:
            eng.run(["git", "fetch"], repo, quiet=True)
        except eng.LitterboxError as e:
            eng.LOG(f"WARNING: could not check the vault for newer changes. {e}")
    locks = eng.get_locks(repo, strict=True)
    group = files + [eng.record_relpath(pn)]
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
    for old, new in sorted(pairs, key=lambda pair: (_ext(pair[0]) in DRAWING_EXTENSIONS, _name(pair[0]).lower())):
        src, dst = _abs(repo, old), _abs(repo, new)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if _ext(old) in SOLIDWORKS_EXTENSIONS:
            log(f"Copying {_name(old)} as {_name(new)}")
            backend.copy(src, dst)
        else:
            shutil.copyfile(src, dst)
        if not os.path.exists(dst) or (os.path.getsize(dst) == 0 and os.path.getsize(src) > 0):
            raise RevisionFailed(f"The copy {new} was not created properly.")
        if _ext(old) in MODEL_EXTENSIONS:
            new_model[_name(old).lower()] = dst
        elif _ext(old) in DRAWING_EXTENSIONS:
            _repoint_drawing(dst, new_model, backend)


def _repoint_drawing(drawing, new_model, backend):
    """Make a copied drawing refer to the copied model instead of the original."""
    for stored, found in backend.references(drawing):
        target = new_model.get(_name(stored or found).lower())
        if target is None:
            continue
        if not backend.repoint(drawing, stored, target):
            raise RevisionFailed(f"SolidWorks would not change the reference inside {_name(drawing)}.")
    for stored, found in backend.references(drawing):
        if _name(stored or found).lower() in new_model:
            raise RevisionFailed(f"{_name(drawing)} still refers to the original model.")


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
        eng.run(["git", "rm", "-q", "-f", "--"] + remove, repo)
    eng.run(["git", "add", "--"] + add + [record_path], repo)
    eng.run(["git", "commit", "-m", message, "--"] + add + remove + [record_path], repo)
    eng._push_with_retry(repo)


@eng._converts_errors
def revise(repo, pn, reason, backend=None, log=print):
    """Make the next revision of a released part. Call revise_plan() first and show it to the user.

    Returns the list of the new revision's files. The new revision is checked out to you.
    """
    eng.validate_repo(repo)
    pn = eng._as_pn(pn)
    user = eng.get_user(repo)
    eng._check_permission(repo, user, "revise")
    reason = " ".join((reason or "").split())
    if not reason:
        raise RevisionFailed("A reason is required to revise a part.")
    recover(repo, log)
    plan = revise_plan(repo, pn)
    if not plan.ok:
        raise RevisionFailed(f"{pn} can't be revised yet:\n- " + "\n- ".join(plan.problems))

    record_path = eng.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, new_files, journal = [], [], None
    owns_backend = backend is None
    if owns_backend:
        backend = importer.SolidWorksBackend()
    pushed = False
    try:
        with _com_thread():
            eng._lock(repo, record_path, pn)                  # whoever gets this lock gets the revision
            locked.append(record_path)
            eng._pull(repo)                                   # lock first, THEN pull
            record = registry.load(repo, pn)
            files = registry.cad_files(repo, pn, record.revision)
            if registry.can_revise(record) or record.revision != plan.revision:
                raise RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            copies, _kept, problems = _copy_list(repo, record, files)
            if problems:
                raise RevisionFailed("\n".join(problems))
            new_files = [new for _old, new in copies]
            journal = {"op": "revise", "token": token, "record": record_path, "added": new_files,
                       "removed": [], "locked": []}
            _write_journal(repo, journal)

            log(f"Revising {pn} from Rev {record.revision} to Rev {registry.next_free_revision(record)}...")
            _copy_set(repo, copies, backend, log)
            registry.mark_revised(record, user, reason, new_files)
            registry.save(repo, record)
            message = f"{pn}: Revised to Rev {record.revision} - {reason}\n\nLitterbox-Revise: {token}"
            _commit_and_push(repo, message, new_files, [], record_path)
            pushed = True

            for rel in new_files:                             # the new revision is yours to work on
                eng._lock(repo, rel, pn)
                locked.append(rel)
    except BaseException:
        if pushed:
            # The revision exists in the vault. Do not undo it; just say what is left to do.
            eng._force_unlock_quietly(repo, locked)
            _clear_journal(repo)
            eng.enforce_read_only(repo)
            raise RevisionFailed(f"Rev {registry.load(repo, pn).revision} of {pn} was created, but it could not be "
                                 "checked out to you. Click Check Out to continue.") from None
        try:
            if journal is not None:
                journal["locked"] = locked
                _undo(repo, journal, log)
            else:
                eng._force_unlock_quietly(repo, locked)
        finally:
            _clear_journal(repo)
        raise
    finally:
        if owns_backend:
            backend.close()
    _clear_journal(repo)
    eng.enforce_read_only(repo)
    return new_files


# ---------------------------------------------------------------------------
# Cancel Revision
# ---------------------------------------------------------------------------

@eng._converts_errors
def cancel_revision(repo, pn, reason, backend=None, log=print):
    """Throw away the working revision (keeping its files in cancelled-revs). Returns the kept files.

    Call cancel_revision_plan() first and show it to the user. The part goes back to its latest
    released revision, and the cancelled letter is never used again."""
    eng.validate_repo(repo)
    pn = eng._as_pn(pn)
    user = eng.get_user(repo)
    eng._check_permission(repo, user, "cancel_revision")
    reason = " ".join((reason or "").split())
    if not reason:
        raise RevisionFailed("A reason is required to cancel a revision.")
    recover(repo, log)
    plan = cancel_revision_plan(repo, pn)
    if not plan.ok:
        raise RevisionFailed(f"The revision of {pn} can't be cancelled yet:\n- " + "\n- ".join(plan.problems))

    record_path = eng.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, journal = [], None
    owns_backend = backend is None
    if owns_backend:
        backend = importer.SolidWorksBackend()
    pushed = False
    kept = []
    try:
        with _com_thread():
            eng._lock(repo, record_path, pn)
            locked.append(record_path)
            eng._pull(repo)
            record = registry.load(repo, pn)
            if registry.can_cancel_revision(record) or record.revision != plan.revision:
                raise RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            files = registry.cad_files(repo, pn, record.revision)
            for rel in files:                                 # nobody else may pick the files up meanwhile
                eng._lock(repo, rel, pn)
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
            registry.mark_revision_cancelled(record, user, reason, kept)
            registry.save(repo, record)
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
                eng._force_unlock_quietly(repo, locked)
        finally:
            _clear_journal(repo)
        raise
    finally:
        if owns_backend:
            backend.close()
    _clear_journal(repo)
    # the cancelled files are gone from cad, so their locks (and the record's) can go
    eng._force_unlock_quietly(repo, [rel for rel in locked if rel != record_path])
    failed = eng._unlock_mine(repo, [record_path])
    eng.enforce_read_only(repo)
    if failed:
        raise RevisionFailed(eng._unlock_failure_message(failed))
    return kept
