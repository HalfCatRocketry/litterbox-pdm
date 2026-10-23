"""
revise.py - Revise: make the next revision of a released part (B after A), as copies of its files
under the new letter. The released revision stays as it was.
"""

import uuid
from dataclasses import dataclass, field

from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_backend
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.parts import planning
from litterbox.parts import revision_files
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_revisions
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


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
    copies, kept, more = revision_files.copy_list(repo, record, files)
    problems += [p for p in more if p not in problems]
    return RevisePlan(pn, record.name, record.revision, record_revisions.next_free_revision(record),
                      files, copies, kept, problems)


@converts_errors
def revise(repo, pn, reason, backend=None, log=print):
    """Make the next revision of a released part. Call revise_plan() first and show it to the user.

    Returns the list of the new revision's files. The new revision is checked out to you.
    """
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "revise")
    permission_check.check_parts(repo, [pn], "revise")
    if permission_check.uses_solidworks(repo, [pn]):
        permission_check.check_solidworks_version(repo, f"revise {pn}")
    reason = " ".join((reason or "").split())
    if not reason:
        raise revision_files.RevisionFailed("A reason is required to revise a part.")
    revision_files.recover(repo, log)
    plan = revise_plan(repo, pn)
    if not plan.ok:
        raise revision_files.RevisionFailed(f"{pn} can't be revised yet:\n- " + "\n- ".join(plan.problems))

    record_path = record_store.record_relpath(pn)
    token = uuid.uuid4().hex[:12]
    locked, new_files, journal = [], [], None
    owns_backend = backend is None
    if owns_backend:
        backend = sw_backend.SolidWorksBackend()
    pushed = False
    try:
        with com.com_thread():
            lfs_locks.lock(repo, record_path, pn)                  # whoever gets this lock gets the revision
            locked.append(record_path)
            remote.pull(repo)                                   # lock first, THEN pull
            record = record_store.load(repo, pn)
            files = record_files.cad_files(repo, pn, record.revision)
            lfs_download.download(repo, files, f"{pn} Rev {record.revision} to copy")    # SolidWorks copies the real files
            if record_revisions.can_revise(record) or record.revision != plan.revision:
                raise revision_files.RevisionFailed(f"{pn} was changed by someone else a moment ago. Run Get Latest and try again.")
            copies, _kept, problems = revision_files.copy_list(repo, record, files)
            if problems:
                raise revision_files.RevisionFailed("\n".join(problems))
            new_files = [new for _old, new in copies]
            journal = {"op": "revise", "token": token, "record": record_path, "added": new_files,
                       "removed": [], "locked": []}
            revision_files.write_journal(repo, journal)

            log(f"Revising {pn} from Rev {record.revision} to Rev {record_revisions.next_free_revision(record)}...")
            revision_files.copy_set(repo, copies, backend, log)
            record_revisions.mark_revised(record, user, reason, new_files)
            record_store.save(repo, record)
            message = f"{pn}: Revised to Rev {record.revision} - {reason}\n\nLitterbox-Revise: {token}"
            revision_files.commit_and_push(repo, message, new_files, [], record_path)
            pushed = True

            for rel in new_files:                             # the new revision is yours to work on
                lfs_locks.lock(repo, rel, pn)
                locked.append(rel)
    except BaseException:
        if pushed:
            # The revision exists in the vault. Do not undo it; just say what is left to do.
            lfs_locks.force_unlock_quietly(repo, locked)
            revision_files.clear_journal(repo)
            read_only.enforce_read_only(repo)
            raise revision_files.RevisionFailed(f"Rev {record_store.load(repo, pn).revision} of {pn} was created, but it could not be "
                                 "checked out to you. Click Check Out to continue.") from None
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
    read_only.enforce_read_only(repo)
    return new_files
