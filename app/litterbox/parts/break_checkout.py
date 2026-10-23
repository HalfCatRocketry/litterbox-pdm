"""
break_checkout.py - Break Checkout (Admin and Owner): take a part back from whoever has it checked out, when the org
needs it and they can't check it in (away, left, lost their computer).

Their locks on the part's record and files are released, and the part's history says who broke it, whose it was and
why. Their changes are not uploaded: they only exist on their computer. Litterbox there keeps them safe: their next
sync puts the part's files back as they are in the vault and saves their versions of the CAD files beside the vault
(git/remote.py: set_aside_broken_checkouts), and they can check the part out again to carry on.
"""

from pathlib import Path

from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_store


def held_by_others(repo, pn, locks=None):
    """{path: owner} for the part's record and files (every revision) that someone else has locked."""
    locks = lfs_locks.get_locks(repo, strict=True) if locks is None else locks
    paths = [record_store.record_relpath(pn)] + record_files.all_cad_files(repo, pn)
    return {path: locks[path.lower()][1] for path in paths
            if path.lower() in locks and locks[path.lower()][0] != "you"}


@converts_errors
def _ids_of(repo, host_names):
    """The team ids of the people whose locks these are (lock owners are host account names); [] without a team."""
    try:
        directory = team_store.load(repo)
    except LitterboxError:
        return []
    found = [directory.find_by_host_name(name) for name in host_names] if directory is not None else []
    return [person.id for person in found if person is not None]


def break_checkout(repo, pn, reason):
    """Release everyone else's locks on a part and note it in its history. A reason is required. Returns the names
    of the people whose checkout was broken."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "break_checkout")
    permission_check.check_parts(repo, [pn], "break_checkout")
    reason = batch_core.one_line(reason)
    if not reason:
        raise LitterboxError("Say why the checkout is being broken.")
    if not (Path(repo) / record_store.record_relpath(pn)).is_file():
        raise LitterboxError(f"There is no record for {pn} in your copy of the vault. Try Get Latest first.")
    held = held_by_others(repo, pn)
    if not held:
        raise LitterboxError(f"Nobody else has {pn} checked out, so there is nothing to break.")
    owners = sorted(set(held.values()))
    lfs_locks.force_unlock(repo, list(held))
    who = ", ".join(owners)
    of_ids = _ids_of(repo, owners)
    batch_core.edit_record(
        repo, pn, "break_checkout",
        lambda record, by: record_lifecycle.add_event(record, record_model.EVENT_CHECKOUT_BROKEN, by, of=who,
                                                       of_ids=of_ids or None, reason=reason),
        f"{pn}: Checkout by {who} broken - {reason}")
    return owners
