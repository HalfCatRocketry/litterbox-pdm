"""
reference_replace.py - Update references: point assemblies that are still in work at the latest
released revision of the parts they use. Released assemblies are frozen: to change one, revise it.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.cad import file_types
from litterbox.cad.solidworks import com
from litterbox.core import filenames
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import undoing
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import reference_model
from litterbox.references import reference_reader


@dataclass
class Replacement:
    """Point `parent`'s working revision at the child's latest released revision."""
    parent: PN
    child: PN
    old_revision: str


@dataclass
class ReplaceResult:
    parent: PN
    status: str                 # done, left_checked_out, skipped, failed
    message: str = ""
    children: list = field(default_factory=list)


def replacements_from(uses_list):
    return [Replacement(u.parent, u.child, u.child_revision) for u in uses_list if u.replaceable]


def _model_file(repo, child, revision):
    models = [f for f in record_files.cad_files(repo, child, revision) if file_types.extension(f) in file_types.MODEL_EXTENSIONS]
    return models[0] if models else None


def _repoint_file(repo, rel, replacements, backend):
    """Change the references inside one assembly file. Returns how many were changed."""
    path = os.path.join(str(repo), rel)
    changed = 0
    for replacement, old_name, new_path in replacements:
        done = False
        for stored, located in backend.references(path):
            if file_types.file_name(stored or located).lower() == old_name.lower():
                if not backend.repoint(path, stored, new_path):
                    raise reference_model.ReferencesError(f"SolidWorks would not change the reference to {old_name} inside "
                                          f"{file_types.file_name(rel)}.")
                done = True
        changed += done
    for replacement, old_name, _new in replacements:
        for stored, located in backend.references(path):
            if file_types.file_name(stored or located).lower() == old_name.lower():
                raise reference_model.ReferencesError(f"{file_types.file_name(rel)} still refers to {old_name}.")
    return changed


def replace_references(repo, replacements, comment="Updated to the latest released parts", backend=None,
                       log=print):
    """Point assemblies that are still in work at the latest released revision of the parts they use.

    For each assembly: if nobody has it checked out, Litterbox checks it out, changes it, and checks it in
    (one commit each). If you already have it checked out, the change is made in your copy and left for you to
    check in. If someone else has it, it is skipped. A failure on one assembly never stops the others and
    never leaves it half done. All the check-outs share one download and all the check-ins share one upload.
    Returns a ReplaceResult per assembly.
    """
    repository.validate_repo(repo)
    by_parent = {}
    for item in replacements:
        by_parent.setdefault(item.parent, []).append(item)

    owns_backend = backend is None
    results = {}
    try:
        if owns_backend and by_parent:
            backend = reference_reader.new_backend()
        reader = reference_reader.make_reader(backend, log)
        with com.com_thread():
            _replace_in_all(repo, by_parent, comment, backend, reader, log, results)
    finally:
        if owns_backend and backend is not None:
            backend.close()
    return [results[parent] for parent in sorted(by_parent) if parent in results]


def _plan_replacement(repo, parent, items, locks):
    """What to change in one assembly, worked out before anything is locked. Returns a ReplaceResult if there is
    nothing to do (or it can't be done), else (revision, edits, names, user_checked_out)."""
    try:
        record = record_store.load(repo, parent)
        if record.status != record_model.STATUS_IN_WORK or record.cots:
            return ReplaceResult(parent, "skipped", f"Rev {record.revision} is {record.status}, so it can't be changed.")
        lock = locks.get(record_store.record_relpath(parent).lower())
        if lock and lock[0] != "you":
            return ReplaceResult(parent, "skipped", f"Checked out by {lock[1]}.")

        edits, names = [], []
        for item in items:
            child_record = record_store.load(repo, item.child)
            latest = child_record.released_revision
            if not latest or latest == item.old_revision:
                continue
            new_rel = _model_file(repo, item.child, latest)
            if new_rel is None:
                return ReplaceResult(parent, "failed", f"Rev {latest} of {item.child} has no model file here. "
                                                         "Run Get Latest.")
            if read_only.is_pointer(Path(repo) / new_rel):
                return ReplaceResult(parent, "failed", f"{new_rel} has not been downloaded. Run Get Latest.")
            old_name = filenames.filename(item.child, item.old_revision, file_types.extension(new_rel))
            edits.append((item, old_name, os.path.join(str(repo), new_rel)))
            names.append(f"{item.child} Rev {item.old_revision} -> {latest}")
        if not edits:
            return ReplaceResult(parent, "skipped", "Nothing to change.")
        return record.revision, edits, names, bool(lock)
    except Exception as e:
        return ReplaceResult(parent, "failed", str(e))


def _replace_in_all(repo, by_parent, comment, backend, reader, log, results):
    jobs = {}
    try:
        locks = lfs_locks.get_locks(repo, strict=True)
    except LitterboxError as e:
        for parent in by_parent:
            results[parent] = ReplaceResult(parent, "failed", str(e))
        return
    for parent in sorted(by_parent):
        outcome = _plan_replacement(repo, parent, by_parent[parent], locks)
        if isinstance(outcome, ReplaceResult):
            results[parent] = outcome
        else:
            jobs[parent] = outcome

    ours = [parent for parent, job in jobs.items() if not job[3]]          # the ones we have to check out
    if ours:
        log("Checking out " + ", ".join(map(str, ours)) + " to update their references")
        try:
            _done, failed = checkout.checkout_many(repo, ours)
        except Exception as e:
            failed = [(parent, str(e)) for parent in ours]
        for parent, why in failed:
            if parent in jobs:
                results[parent] = ReplaceResult(parent, "failed", why)
                del jobs[parent]
                ours.remove(parent)

    undo = []
    for parent, (revision, edits, names, user_checked_out) in list(jobs.items()):
        try:
            files = [f for f in record_files.cad_files(repo, parent, revision) if file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS]
            if not files:
                raise reference_model.ReferencesError(f"{parent} has no assembly file in Rev {revision}.")
            changed = 0
            for rel in files:
                log(f"Updating {file_types.file_name(rel)}")
                changed += _repoint_file(repo, rel, edits, backend)
            if not changed:
                raise reference_model.ReferencesError("None of those parts are in the assembly file any more. Check In the assembly "
                                      "so its list of parts is refreshed.")
        except Exception as e:
            results[parent] = ReplaceResult(parent, "failed", str(e))
            del jobs[parent]
            if parent in ours:
                undo.append(parent)
                ours.remove(parent)
    if undo:
        try:
            undoing.undo_checkout_many(repo, undo)
        except Exception as e:
            log(f"WARNING: could not undo the check-out of {', '.join(map(str, undo))}: {e}")

    for parent, (_revision, _edits, names, user_checked_out) in jobs.items():
        if user_checked_out:
            results[parent] = ReplaceResult(parent, "left_checked_out",
                                            "Changed in your copy. Check it in to save the change.", names)
    if ours:
        try:
            _done, failed = checkin.checkin_many(repo, ours, comment, references_reader=reader)
        except Exception as e:
            failed = [(parent, str(e)) for parent in ours]
        failures = dict(failed)
        notice = failures.pop("Locks", None)          # saved, but a lock could not be released
        for parent in ours:
            if parent in failures:
                log(f"WARNING: the change to {parent} could not be checked in: {failures[parent]}")
                results[parent] = ReplaceResult(
                    parent, "left_checked_out",
                    f"Changed and still checked out to you, but the check-in failed: {failures[parent]}", jobs[parent][2])
            elif notice:
                results[parent] = ReplaceResult(parent, "left_checked_out", notice, jobs[parent][2])
            else:
                results[parent] = ReplaceResult(parent, "done", "Updated and checked in.", jobs[parent][2])
