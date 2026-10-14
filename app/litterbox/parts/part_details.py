"""
part_details.py - Edit Details: change a part's name and
description.
"""

from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import registry
from litterbox.records.error_conversion import converts_errors


@converts_errors
def edit_details(repo, pn, name, description):
    """Change a part's name and description. You must have the part checked out.

    The change is made in your copy of the record only. It is uploaded with your next
    Save Progress or Check In (and thrown away by Undo Checkout). Returns True if
    anything changed.
    """
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "edit_details")
    if not lfs_locks.is_mine(lfs_locks.get_locks(repo, strict=True), registry.record_relpath(pn)):
        raise LitterboxError(f"You don't have {pn} checked out. Check it out to change its name or description.")
    record = registry.load(repo, pn)
    changed = registry.edit_details(record, user, name, description) is not None
    if changed:
        registry.save(repo, record)
    return changed
