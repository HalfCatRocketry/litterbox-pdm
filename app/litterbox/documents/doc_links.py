"""
doc_links.py - linking documents to part revisions (records/record_links.py keeps them in the part's record).

- A part you have checked out: add and remove links freely on its working revision. The change goes up with your
  next Save Progress or Check In, like Edit Details.
- A released part: an Admin or a superuser may add a link at any time (a document that wasn't ready at release).
  It is uploaded at once, under a short lock, and recorded. Taking a link off a released part needs sign-offs: a
  Remove document link workflow (workflows/, action remove_document).

A void document can't be linked. Links point at the document, whose latest released revision is what a reader wants.
"""

from litterbox.core.doc_number import DocNumber
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_links
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_identity


def may_link_released(repo):
    """(True, "") if you may add a link to a released part (an Admin, the Owner or a superuser), else (False, why)."""
    identity = team_identity.current(repo)
    if identity.allows("link_released_documents")[0]:
        return True, ""
    directory, person = getattr(identity, "directory", None), getattr(identity, "person", None)
    if directory is not None and person is not None and directory.is_superuser(person):
        return True, ""
    return False, "Only an Admin or a superuser can link a document to a released part."


def _document(repo, number):
    number = batch_core.as_pn(number)
    if not isinstance(number, DocNumber):
        raise LitterboxError(f"{number} isn't a document.")
    document = record_store.load(repo, number)
    if document.status == record_model.STATUS_VOID:
        raise LitterboxError(f"{number} is void, so it can't be linked.")
    return number


def _part(repo, pn):
    pn = batch_core.as_pn(pn)
    if isinstance(pn, DocNumber):
        raise LitterboxError("Documents are linked to parts, not to other documents.")
    return pn


def _your_checkout(repo, pn, user):
    permission_check.check_permission(repo, user, "edit_details")
    if not lfs_locks.is_mine(lfs_locks.get_locks(repo, strict=True), record_store.record_relpath(pn)):
        raise LitterboxError(f"You don't have {pn} checked out. Check it out to change its documents.")
    record = record_store.load(repo, pn)
    if record.status != record_model.STATUS_IN_WORK:
        raise LitterboxError(f"{pn} is {record.status}.")
    return record


@converts_errors
def link(repo, pn, number):
    """Link a document to the working revision of a part you have checked out. Returns True if it changed."""
    repository.validate_repo(repo)
    pn, number = _part(repo, pn), _document(repo, number)
    user = repository.get_user(repo)
    record = _your_checkout(repo, pn, user)
    changed = record_links.link(record, user, number) is not None
    if changed:
        record_store.save(repo, record)
    return changed


@converts_errors
def unlink(repo, pn, number):
    """Take a document's link off the working revision of a part you have checked out."""
    repository.validate_repo(repo)
    pn = _part(repo, pn)
    user = repository.get_user(repo)
    record = _your_checkout(repo, pn, user)
    record_links.unlink(record, user, number)
    record_store.save(repo, record)


@converts_errors
def link_released(repo, pn, number):
    """An Admin or superuser links a document to a released part's revision, uploaded at once."""
    repository.validate_repo(repo)
    pn, number = _part(repo, pn), _document(repo, number)
    allowed, why = may_link_released(repo)
    if not allowed:
        raise LitterboxError(why)
    superuser = not team_identity.current(repo).allows("link_released_documents")[0]

    def edit(record, user):
        if record.status != record_model.STATUS_RELEASED:
            raise record_model.RegistryError(f"{record.pn} isn't released: check it out and link the document there.")
        if record_links.link(record, user, number, admin=True if not superuser else None,
                             superuser=True if superuser else None) is None:
            raise record_model.RegistryError(f"{number} is already linked to {record.pn} Rev {record.revision}.")

    batch_core.edit_record(repo, pn, "checkin", edit, f"{pn}: Linked {number}" +
                           (" (superuser)" if superuser else " (Admin)"))
