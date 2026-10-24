"""
part_details.py - Edit Details: change a part's name and description, and switch it between CAD and non-CAD
(only before it is ever released, and while it has no SolidWorks files).
"""

from litterbox.core import file_types
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


def has_cad_files(repo, pn):
    """True if any revision of the part has a SolidWorks file in the cad folder."""
    return any(file_types.extension(f) in file_types.CAD_EXTENSIONS for f in record_files.all_cad_files(repo, pn))


@converts_errors
def edit_details(repo, pn, name, description, kind=None):
    """Change a part's name and description, and with `kind` its kind (record_model.KIND_CAD or KIND_NONCAD). You
    must have the part checked out.

    The change is made in your copy of the record only. It is uploaded with your next
    Save Progress or Check In (and thrown away by Undo Checkout). Returns True if
    anything changed.
    """
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "edit_details")
    permission_check.check_parts(repo, [pn], "edit_details")
    if not lfs_locks.is_mine(lfs_locks.get_locks(repo, strict=True), record_store.record_relpath(pn)):
        raise LitterboxError(f"You don't have {pn} checked out. Check it out to change its name or description.")
    record = record_store.load(repo, pn)
    changed = record_lifecycle.edit_details(record, user, name, description) is not None
    if kind is not None and kind != record.kind:
        changed = record_lifecycle.change_kind(record, user, kind, has_cad_files(repo, pn)) is not None or changed
    if changed:
        record_store.save(repo, record)
    return changed
