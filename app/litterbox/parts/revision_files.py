"""
revision_files.py - what Revise and Cancel Revision share: copying a revision's files under their new
names (through SolidWorks, so references are updated), pointing a drawing at the new model, committing, and the
journal that lets an attempt that stopped half way be put back (recover).
"""

import os
import shutil
from pathlib import Path

from litterbox import layout
from litterbox.cad import file_types
from litterbox.core import doc_number
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.importing import import_journal
from litterbox.records import record_revisions
from litterbox.team import guarded_push
from litterbox.util import journal as journal_file


JOURNAL_NAME = "litterbox-revise.json"


JOURNAL_VERSION = 1


class RevisionFailed(LitterboxError):
    """Revise or Cancel Revision could not be completed. Nothing was changed."""


def abs_path(repo, rel):
    return str(Path(repo) / rel)


def _journal_path(repo):
    return journal_file.path(repo, JOURNAL_NAME)


def write_journal(repo, data):
    journal_file.write(repo, JOURNAL_NAME, dict(data, version=JOURNAL_VERSION))


def clear_journal(repo):
    journal_file.clear(repo, JOURNAL_NAME)


def read_journal(repo):
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
    folders = (f"{layout.CAD_DIR_NAME}/", f"{layout.DOC_DIR_NAME}/", f"{layout.CANCELLED_DIR_NAME}/")
    for rel in journal["added"] + journal["removed"]:
        if not str(rel).startswith(folders) or ".." in str(rel):
            raise RevisionFailed(f"The note about an unfinished revise lists a file outside the cad and "
                                 f"cancelled-revs folders ({rel}). Litterbox will not touch it. "
                                 f"Check {path} by hand.")
    if not journal["record"].startswith((f"{layout.LOG_DIR_NAME}/", f"{layout.DOC_LOG_DIR_NAME}/")) \
            or ".." in journal["record"]:
        raise RevisionFailed(f"The note about an unfinished revise lists a record outside PN-logs. Check {path}.")
    return journal


def undo_attempt(repo, journal, log=print):
    """Put the vault back as it was before an attempt: our unpushed commit, new files, removed files, locks.
    Never deletes anything that the latest commit has. Returns 'cleaned' or 'finished'."""
    token = journal["token"]
    commit = import_journal.our_commit(repo, token)
    if commit:
        if import_journal.unpushed(repo) == 0:
            return "finished"                           # the attempt had reached the vault: keep it
        if repository.quiet_output(repo, "rev-parse", "HEAD") != commit:
            raise RevisionFailed("An unfinished revise left a commit that has not been pushed, but it is no "
                                 "longer the latest commit, so Litterbox will not undo it. Ask for help.")
        runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
    record, added, removed = journal["record"], journal["added"], journal["removed"]
    # put back anything the attempt took out of the vault, and the record
    in_head = repository.in_head_many(repo, added + removed)
    gone = [rel for rel in removed if rel in in_head]
    try:
        if gone:
            runner.run(["git", "reset", "-q", "HEAD", "--"] + gone, repo)
            runner.run(["git", "checkout", "HEAD", "--"] + gone, repo)
        runner.run(["git", "restore", "--staged", "--worktree", "--", record], repo)
    except LitterboxError as e:
        log(f"WARNING: could not fully restore the vault's files: {e}")
    # remove the new files, but only ones the vault does not own
    ours = [rel for rel in added if rel not in in_head]
    if ours:
        try:
            runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--"] + ours, repo)
        except LitterboxError as e:
            log(f"WARNING: could not fully clean git's index: {e}")
    problems = read_only.delete_files(repo, ours)
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


def give_up(repo, journal, locked, log=print):
    """After a Revise or Cancel Revision failed before its upload: put back what the attempt did (or, if it had not
    started changing files yet, just give back the locks taken), then forget the journal."""
    try:
        if journal is not None:
            journal["locked"] = locked
            undo_attempt(repo, journal, log)
        else:
            lfs_locks.force_unlock_quietly(repo, locked)
    finally:
        clear_journal(repo)


def recover(repo, log=print):
    """Clean up after a revise or cancel that was interrupted. Returns 'nothing', 'cleaned' or 'finished'."""
    repository.validate_repo(repo)
    journal = read_journal(repo)
    if journal is None:
        return "nothing"
    result = undo_attempt(repo, journal, log)
    clear_journal(repo)
    if result == "finished":
        log("The unfinished revise had actually reached the vault, so it was kept.")
    return result


def revised_name(rel, new_revision):
    """The name of a file of the next revision: cad/HCR-00042-001_B.SLDPRT, or documents/PROP-0001_B.docx."""
    if rel.startswith(f"{layout.DOC_DIR_NAME}/"):
        number, _rev, _ext = doc_number.parse_filename(rel)
        return f"{layout.DOC_DIR_NAME}/{doc_number.filename(number, new_revision, rel.rsplit('.', 1)[1])}"
    file_pn, _rev, ext = filenames.parse_filename(rel)
    return f"{layout.CAD_DIR_NAME}/{filenames.filename(file_pn, new_revision, ext)}"


def copy_list(repo, record, files):
    """([(old, new)], kept, problems) for revising the given files to the next letter. A part's SolidWorks files
    are copied and the rest (its STEP and PDF) stay with the old revision; every file of a document is copied."""
    new_revision = record_revisions.next_free_revision(record)
    copies, kept, problems = [], [], []
    for rel in files:
        if record.is_document or file_types.extension(rel) in file_types.SOLIDWORKS_EXTENSIONS:
            new = revised_name(rel, new_revision)
            copies.append((rel, new))
            if (Path(repo) / new).exists():
                problems.append(f"{new} already exists in the cad folder.")
        else:
            kept.append(rel)
    if record.uses_cad and not any(
            file_types.extension(old) in file_types.MODEL_EXTENSIONS for old, _new in copies):
        problems.append("There is no SolidWorks part or assembly file to copy.")
    return copies, kept, problems


def cancelled_name(rel):
    return f"{layout.CANCELLED_DIR_NAME}/{layout.CANCELLED_PREFIX}{file_types.file_name(rel)}"


def copy_set(repo, pairs, backend, log):
    """Copy each (old, new) pair: SolidWorks files with SolidWorks, others as plain files.
    Drawings are re-pointed at the copy of the model they were drawn from."""
    new_model = {}
    for old, new in sorted(pairs, key=lambda pair: (file_types.extension(pair[0]) in file_types.DRAWING_EXTENSIONS, file_types.file_name(pair[0]).lower())):
        src, dst = abs_path(repo, old), abs_path(repo, new)
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
            repoint_drawing(dst, new_model, backend)


def repoint_drawing(drawing, new_model, backend):
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


def commit_and_push(repo, message, add, remove, record_path):
    if remove:
        for rel in remove:
            try:
                os.chmod(Path(repo) / rel, 0o644)
            except OSError:
                pass
        runner.run(["git", "rm", "-q", "-f", "--"] + remove, repo)
    runner.run(["git", "add", "--"] + add + [record_path], repo)
    runner.run(["git", "commit", "-m", message, "--"] + add + remove + [record_path], repo)
    guarded_push.push(repo)
