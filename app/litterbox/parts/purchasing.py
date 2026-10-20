"""
purchasing.py - Purchasing Info: change a part's supplier, supplier part number, unit cost and lead time
(records/purchasing_info.py).

Purchasing information is not part of the design, so it doesn't need a check-out and works on released and COTS
parts too. A part nobody has checked out is changed and uploaded at once (one commit, under the record's lock, as
Release does). A part you have checked out is changed in your copy only, like Edit Details, and goes up with your
next Save Progress or Check In. A part someone else has checked out has to wait until they check it in.
"""

from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_lifecycle
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors

ACTION = "edit_purchasing"
UPLOADED, SAVED_LOCALLY, UNCHANGED = "uploaded", "saved", "unchanged"


@converts_errors
def edit_purchasing(repo, pn, fields):
    """Change the part's purchasing fields ({name: text}, see purchasing_info.FIELDS). Returns UPLOADED (changed
    in the vault), SAVED_LOCALLY (you have it checked out: it goes up with your next check-in) or UNCHANGED."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, ACTION)
    path = record_store.record_relpath(pn)
    owner = lfs_locks.get_locks(repo, strict=True).get(path.lower(), ("", ""))[0]
    if owner == "you":
        record = record_store.load(repo, pn)
        if record_lifecycle.edit_purchasing(record, user, fields) is None:
            return UNCHANGED
        record_store.save(repo, record)
        return SAVED_LOCALLY
    if owner:
        raise LitterboxError(f"{pn} is checked out by {owner}. Its purchasing information can be changed when they "
                             "check it in (or by them, meanwhile).")
    record = record_store.load(repo, pn)
    if record_lifecycle.edit_purchasing(record, user, fields) is None:    # a dry run on your copy: anything to do?
        return UNCHANGED

    def edit(latest, by):
        if record_lifecycle.edit_purchasing(latest, by, fields) is None:
            raise LitterboxError(f"{pn}: somebody else made the same change meanwhile.")

    batch_core.edit_record(repo, pn, ACTION, edit, f"{pn}: Purchasing info changed")
    return UPLOADED
