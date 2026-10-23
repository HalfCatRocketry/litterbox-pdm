"""
doc_create.py - New Document: give a document of one of the org's types its number (PROP-0001, the next free one
for the type's prefix) by creating its record in DOC-logs/, committing and pushing it.

If someone else takes the same number first, the push fails and Litterbox takes the next one and tries again, as
New Part does. The document starts with no files: check it out and use Add Files... (doc_files.py).
"""


from litterbox import diagnostics
from litterbox.core import doc_number
from litterbox.documents import doc_types
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import create
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors


ATTEMPTS = 5


def type_for(repo, key):
    """The DocType with this key, if New Document may use it (it exists and isn't hidden)."""
    found = doc_types.by_key(doc_types.load(repo)).get(key)
    if found is None:
        raise doc_types.DocTypeError("There is no such document type. Run Get Latest, or ask an Admin to add it "
                                     "(Team > Document Types...).")
    if found.hidden:
        raise doc_types.DocTypeError(f"{found.name} documents are no longer made (the type is hidden).")
    return found


def next_number(repo, prefix):
    """The number after the highest one with this prefix (numbers are never reused, even a void document's)."""
    return doc_number.next_number(prefix, record_store.list_docs(repo))


@converts_errors
def new_document(repo, type_key, title, description=""):
    """Create a document of this type and return its DocNumber. The title is required."""
    repository.validate_repo(repo)
    title = create.clean_name(title)
    description = create.clean_description(description)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "create")
    try:
        remote.sync(repo)
    except LitterboxError as e:
        raise LitterboxError(f"Could not get the latest from the vault, so nothing was created. Are you online?\n\n{e}")
    last_error = None
    for _attempt in range(ATTEMPTS):
        kind = type_for(repo, type_key)                 # read again each time: the vault may have just changed
        number = next_number(repo, kind.prefix)
        rel = record_store.record_relpath(number)
        try:
            record_store.create_record(repo, number, title, user, description=description, doc_type=kind.key)
        except record_model.PNExistsError:
            raise LitterboxError(f"{number} already exists in your copy of the vault. Run Get Latest.") from None
        committed = False
        try:
            runner.run(["git", "add", "--", rel], repo)
            runner.run(["git", "commit", "-m", f"{number}: Created - {title}", "--", rel], repo)
            committed = True
            runner.run(["git", "push"], repo)
        except LitterboxError as e:
            create.undo_creation(repo, rel, committed)
            if not committed:
                raise
            last_error = e
            diagnostics.LOG(f"{number} could not be pushed (someone else may have just used it). Checking again...")
            remote.sync(repo)
            continue
        except BaseException:
            create.undo_creation(repo, rel, committed)
            raise
        read_only.enforce_read_only(repo)
        return number
    raise LitterboxError(f"Could not create a document number after {ATTEMPTS} tries. The last error was:\n\n"
                         f"{last_error}")
