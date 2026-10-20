"""
checkout.py - Check Out: lock a part (record first, then its CAD files)
so you can edit it.

Check out never pushes: the check-out event is written to the record on your computer and uploaded with your
files at check-in.
"""

from dataclasses import dataclass
from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import committing
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


@dataclass
class CheckoutResult:
    files: list                 # the CAD files now checked out to you
    changed_upstream: list      # files that were updated by the download during check-out


@diagnostics.timed("check out")
def _checkout_batch(repo, pns):
    """Check out several parts with one pull: lock every record (several at a time), pull once, lock every part's
    CAD files, log the check-outs. A part that can't be checked out (somebody has it) is left alone and reported;
    the others carry on. If something goes wrong for the whole batch, every lock taken is released."""
    repository.validate_repo(repo)
    pns = batch_core.unique_pns(pns)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "checkout")
    permission_check.check_solidworks_version(
        repo, f"check out {pns[0]}" if len(pns) == 1 else f"check out these {len(pns)} parts")
    batch = batch_core.Batch()
    wanted = []
    for pn in pns:
        if (Path(repo) / record_store.record_relpath(pn)).is_file():
            wanted.append(pn)
        else:
            batch.errors[pn] = LitterboxError(
                f"There is no record for {pn} in your copy of the vault. Try Get Latest first.")
    if not wanted:
        return batch

    got = lfs_locks.lock_many(repo, [(record_store.record_relpath(pn), str(pn)) for pn in wanted])        # whoever gets this lock gets the part
    held = {}                                                                        # pn -> every path locked for it
    for pn in wanted:
        error = got[record_store.record_relpath(pn)]
        if error is None:
            held[pn] = [record_store.record_relpath(pn)]
        else:
            batch.errors[pn] = error
    if not held:
        return batch

    def give_up(pn, error):
        batch.errors[pn] = error
        committing.discard_quietly(repo, [record_store.record_relpath(pn)])
        lfs_locks.force_unlock_quietly(repo, held.pop(pn, []))

    try:
        before = repository.head(repo)
        remote.pull(repo)                           # lock first, THEN pull: never edit a stale copy
        index = record_files.cad_index(repo)      # after the pull, so new files from others are included
        plan = {}
        for pn in list(held):
            try:
                record = record_store.load(repo, pn)           # reload: it may have changed in the pull
            except record_model.RegistryError as e:
                give_up(pn, e)
                continue
            plan[pn] = (record, index.get(pn, {}).get(record.revision, []))

        got = lfs_locks.lock_many(repo, [(f, str(pn)) for pn, (_record, files) in plan.items() for f in files])
        for pn, (record, files) in list(plan.items()):
            held[pn] += [f for f in files if got[f] is None]
            bad = next((got[f] for f in files if got[f] is not None), None)
            if bad is not None:
                give_up(pn, bad)
                del plan[pn]

        try:                                        # download on demand: you can't edit a pointer
            lfs_download.download(repo, [f for _record, files in plan.values() for f in files], "files to check out")
        except LitterboxError as e:
            for pn, (_record, files) in list(plan.items()):
                if lfs_download.stubs(repo, files):
                    give_up(pn, LitterboxError(f"{pn} was not checked out: its files could not be downloaded.\n\n{e}"))
                    del plan[pn]

        changed = set(repository.changed_between(repo, before, repository.head(repo)))
        for pn, (record, files) in list(plan.items()):
            try:
                record_lifecycle.record_checkout(record, user, files)       # refuses released / void parts
                record_store.save(repo, record)
            except record_model.RegistryError as e:
                give_up(pn, e)
                continue
            batch.results[pn] = CheckoutResult(files, [p for p in files if p in changed])
    except BaseException:
        committing.discard_quietly(repo, [record_store.record_relpath(pn) for pn in held])
        lfs_locks.force_unlock_quietly(repo, [path for paths in held.values() for path in paths])
        raise

    read_only.enforce_read_only(repo)
    return batch


@converts_errors
def checkout(repo, pn):
    """Lock a part (record first, then every CAD file), get the latest copy, log the check-out.

    If anything fails, every lock taken so far is released again.
    """
    pn = batch_core.as_pn(pn)
    return batch_core.single(_checkout_batch(repo, [pn]), pn)


@converts_errors
def checkout_many(repo, pns):
    """checkout() for several parts at once, with one download for all of them. Returns (done, failed): done is
    [(pn, CheckoutResult)] and failed is [(pn, message)]. A part somebody else has is reported and skipped."""
    pns = batch_core.unique_pns(pns)
    return batch_core.as_lists(_checkout_batch(repo, pns), pns)
