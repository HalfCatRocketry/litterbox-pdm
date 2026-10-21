"""
record_links.py - the documents linked to a part's revisions (the record's `documents`, {revision: [numbers]}),
changed in memory. The rules for who may change them, and when, are in documents/doc_links.py.

A link belongs to a part revision: it is frozen with it at release and carried to the next revision by Revise
(record_revisions.mark_revised). Each change goes in the part's history.
"""

from litterbox.records import record_lifecycle
from litterbox.records import record_model


EVENT_LINKED = "document_linked"
EVENT_UNLINKED = "document_unlinked"


def linked(record, revision=None):
    """The document numbers (text) linked to a revision of the part, default the working one."""
    return list(record.documents.get(revision or record.revision, []))


def link(record, by, number, revision=None, **details):
    """Link a document to a revision (default the working one). Returns the history entry, or None if it was
    already linked. `details` go on the event (superuser=True, say)."""
    revision = revision or record.revision
    numbers = record.documents.setdefault(revision, [])
    if str(number) in numbers:
        return None
    numbers.append(str(number))
    numbers.sort()
    return record_lifecycle.add_event(record, EVENT_LINKED, by, document=str(number), revision=revision,
                                      **{k: v for k, v in details.items() if v is not None})


def unlink(record, by, number, revision=None, **details):
    """Take a document's link off a revision. Raises RegistryError if it isn't linked. Returns the history entry."""
    revision = revision or record.revision
    numbers = record.documents.get(revision, [])
    if str(number) not in numbers:
        raise record_model.RegistryError(f"{number} isn't linked to {record.pn} Rev {revision}.")
    numbers.remove(str(number))
    if not numbers:
        del record.documents[revision]
    return record_lifecycle.add_event(record, EVENT_UNLINKED, by, document=str(number), revision=revision,
                                      **{k: v for k, v in details.items() if v is not None})
