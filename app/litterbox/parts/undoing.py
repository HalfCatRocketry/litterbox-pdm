"""
undoing.py - Undo Checkout: throw away your changes to a part and give
back its locks.
"""

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import part_changes
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


@diagnostics.timed("undo checkout")
def _undo_batch(repo, pns):
    """Throw away your changes to several parts and release their locks, with one lock list and one restore."""
    repository.validate_repo(repo)
    pns = batch_core.unique_pns(pns)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "undo")
    permission_check.check_parts(repo, pns, "undo")
    batch = batch_core.Batch()

    locks = lfs_locks.get_locks(repo, strict=True)
    index = record_files.cad_index(repo)
    groups = {}
    for pn in pns:
        try:
            record_path = record_store.record_relpath(pn)
            revision = record_store.load(repo, pn).revision
            group = index.get(pn, {}).get(revision, []) + part_changes.gone_files(repo, pn, revision) + [record_path]
            if not any(lfs_locks.is_mine(locks, p) for p in group):
                raise LitterboxError(f"You don't have {pn} checked out.")
            if (repository.count(repo, "@{u}..HEAD", group) or 0) > 0:
                raise LitterboxError(
                    f"Some changes to {pn} were already saved on your computer but not uploaded yet.\n"
                    "Use Check In to upload them. Undo would leave them stranded."
                )
            groups[pn] = group
        except (LitterboxError, record_model.RegistryError) as e:
            batch.errors[pn] = e
    if not groups:
        return batch

    everything = [path for group in groups.values() for path in group]
    tracked = {t.lower() for t in runner.run_chunked(["git", "ls-files"], everything, repo, quiet=True).splitlines()}
    to_restore = [p for p in everything if p.lower() in tracked]
    if to_restore:
        runner.run_chunked(["git", "restore"], to_restore, repo)
        try:            # download on demand: git puts back a pointer; you had the file, so you get it back
            lfs_download.download(repo, [p for p in to_restore if lfs_download.is_stub(repo, p)], "restored files")
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: some restored files could not be downloaded again; they show as not "
                            f"downloaded. {e}")
    for pn, group in groups.items():
        batch.results[pn] = [p for p in group if p.lower() not in tracked]       # never uploaded: kept, not deleted

    failed = lfs_locks.unlock_mine(repo, everything)
    read_only.enforce_read_only(repo)
    if failed:
        batch.notice = lfs_locks.unlock_failure_message(failed)
    return batch


@converts_errors
def undo_checkout(repo, pn):
    """Throw away your changes to a part and release its locks.

    The check-out event is discarded along with the changes. Brand-new files you
    created that were never uploaded are NOT deleted. Their names are returned.
    """
    pn = batch_core.as_pn(pn)
    return batch_core.single(_undo_batch(repo, [pn]), pn)


@converts_errors
def undo_checkout_many(repo, pns):
    """undo_checkout() for several parts at once. Returns (done, failed): done is [(pn, never-uploaded files)]."""
    pns = batch_core.unique_pns(pns)
    return batch_core.as_lists(_undo_batch(repo, pns), pns)
