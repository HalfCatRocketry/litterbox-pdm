"""
batch_core.py - what actions on many parts share.

edit_records is the batch core: one pull, one commit and one push for a whole selection, with every part still
getting its own history entry, and everything put back if the push fails. A part that can't be done is reported
and the rest carry on.
"""

from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox.core.part_number import PN
from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError
from litterbox.git import committing
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.team import guarded_push


def as_pn(value):
    return value if isinstance(value, PN) else parse_pn(value)


@dataclass
class Batch:
    """What a batch action did: results and errors by part, plus a note about locks that could not be released."""
    results: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    notice: str = ""


def unique_pns(pns):
    seen, unique = set(), []
    for value in (pns if isinstance(pns, (list, tuple, set)) else [pns]):
        pn = as_pn(value)
        if pn not in seen:
            seen.add(pn)
            unique.append(pn)
    return unique


def single(batch, pn):
    """The outcome of a batch of one: raise its error, or return its result."""
    if pn in batch.errors:
        raise batch.errors[pn]
    if batch.notice:
        raise LitterboxError(batch.notice)
    return batch.results[pn]


def as_lists(batch, pns):
    """(done, failed) for the window: done is [(pn, result)], failed is [(pn, message)]."""
    done = [(pn, batch.results[pn]) for pn in pns if pn in batch.results]
    failed = [(pn, str(batch.errors[pn])) for pn in pns if pn in batch.errors]
    if batch.notice:
        failed.append(("Locks", batch.notice))
    return done, failed


def batch_message(messages):
    """(subject, body) of the one commit for several records. Each message looks like 'HCR-00001-001: Voided - why'.
    One record keeps its own message. Several get a subject saying what was done to how many, and a body with every
    part's line, so searching the log for a part number still finds it."""
    if len(messages) == 1:
        return messages[0], ""
    what = {message.split(": ", 1)[1] if ": " in message else message for message in messages}
    subject = f"{len(messages)} parts: {what.pop()}" if len(what) == 1 else f"{len(messages)} parts changed"
    return subject, "\n".join(messages)


@diagnostics.timed("record change")
def edit_records(repo, items, atomic=False):
    """Change several records with ONE download and ONE upload.

    `items` is [(pn, action, edit, message)]: `action` is the permission needed, `edit(record, user)` changes the
    record (and raises if the change isn't allowed), `message` is that part's commit message. Every record is
    locked (several at a time), the vault is pulled once, each edit is applied, and everything is committed and
    pushed once, then unlocked.

    A part whose edit is refused (or that somebody else has locked) is left as it was and goes in `errors`; the
    rest carry on. With atomic=True, one refusal stops the whole thing and nothing is changed. If the upload fails,
    every record is put back, the locks are released and the error is raised. All the records go in ONE commit
    (several parts: a subject saying what was done to how many, and a line for each part in the body).
    Returns a Batch: results[pn] is True for each part that was changed.
    """
    repository.validate_repo(repo)
    user = repository.get_user(repo)
    for action in dict.fromkeys(item[1] for item in items):
        permission_check.check_permission(repo, user, action)

    batch, todo, seen = Batch(), [], set()
    for pn, _action, edit, message in items:
        if pn in seen:
            continue
        seen.add(pn)
        path = record_store.record_relpath(pn)
        if (Path(repo) / path).is_file():
            todo.append((pn, path, edit, message))
        else:
            batch.errors[pn] = LitterboxError(
                f"There is no record for {pn} in your copy of the vault. Try Get Latest first.")
    if atomic and batch.errors:
        raise next(iter(batch.errors.values()))
    if not todo:
        return batch

    got = lfs_locks.lock_many(repo, [(path, str(pn)) for pn, path, _edit, _message in todo])
    locked = []
    for entry in todo:
        error = got[entry[1]]
        if error is None:
            locked.append(entry)
        else:
            batch.errors[entry[0]] = error
    paths = [entry[1] for entry in locked]
    if atomic and batch.errors:
        lfs_locks.force_unlock_quietly(repo, paths)
        raise next(iter(batch.errors.values()))
    if not locked:
        return batch

    committed, edited = 0, []
    try:
        remote.pull(repo)
        for pn, path, edit, message in locked:
            try:
                record = record_store.load(repo, pn)       # reload after the pull
                edit(record, user)                     # raises if the change isn't allowed
                record_store.save(repo, record)
            except (LitterboxError, record_model.RegistryError) as e:
                batch.errors[pn] = e
                committing.discard_quietly(repo, [path])
                continue
            edited.append((pn, path, message))
        if atomic and batch.errors:
            raise next(iter(batch.errors.values()))
        if edited:
            edited_paths = [path for _pn, path, _message in edited]
            runner.run_chunked(["git", "add"], edited_paths, repo)
            subject, body = batch_message([message for _pn, _path, message in edited])
            committing.commit_paths(repo, subject, body, edited_paths)    # ONE commit for every record changed
            committed = 1
            guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", f"HEAD~{committed}"], repo)       # take back our unpushed commits
            runner.run_chunked(["git", "restore", "--staged", "--worktree"], paths, repo)
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {', '.join(paths)}: {e}")
        lfs_locks.force_unlock_quietly(repo, paths)
        raise

    for pn, _path, _message in edited:
        batch.results[pn] = True
    failed = lfs_locks.unlock_mine(repo, paths)
    read_only.enforce_read_only(repo)
    if failed:
        batch.notice = lfs_locks.unlock_failure_message(failed)
    return batch


def edit_record(repo, pn, action, edit, message):
    """Lock a record, apply `edit(record, user)`, commit, push, unlock.

    If anything goes wrong the record is put back the way it was and the lock
    is released.
    """
    batch = edit_records(repo, [(pn, action, edit, message)], atomic=True)
    if batch.notice:
        raise LitterboxError(batch.notice)


def one_line(text):
    return " ".join((text or "").split())
