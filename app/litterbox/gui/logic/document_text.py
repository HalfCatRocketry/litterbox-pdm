"""
document_text.py - the Documents screen and a part's Documents tab in words: the table of documents (searched and
filtered by type), the files Open and Remove File offer, the links a part revision has, and which document a link
can be made to.
"""

from pathlib import PurePosixPath

from litterbox.gui.logic import list_view
from litterbox.records import record_model

ALL_TYPES = "All types"

COLUMNS = (("number", "Number", 110), ("title", "Title", 280), ("type", "Type", 170), ("rev", "Rev", 50),
           ("files", "Files", 150), ("state", "Status", 230))

LINK_COLUMNS = (("number", "Document", 110), ("title", "Title", 200), ("type", "Type", 130), ("rev", "Rev", 50),
                ("state", "Status", 140))


def type_name(key, types_by_key):
    """A type's name, or its key when this Litterbox doesn't know it (a hand edit, a newer Litterbox's type)."""
    found = types_by_key.get(key)
    return found.name if found else key


def type_filters(types, rows):
    """The type box's choices: All types, then each type in use or not hidden."""
    used = {row.doc_type for row in rows}
    return [ALL_TYPES] + [t.name for t in types if not t.hidden or t.key in used]


def files_text(files):
    """'DOCX, PDF' for a revision's files."""
    return ", ".join(sorted({PurePosixPath(f).suffix.lstrip(".").upper() for f in files})) or "No files"


def table(rows, types_by_key, search="", type_filter=ALL_TYPES):
    """[(iid, values)] for the Documents screen: document rows (PartStatus), newest number first within a type."""
    shown = list_view.search_rows(rows, search, values=lambda row: (
        str(row.pn), row.name, row.description, type_name(row.doc_type, types_by_key), row.state))
    if type_filter and type_filter != ALL_TYPES:
        shown = [row for row in shown if type_name(row.doc_type, types_by_key) == type_filter]
    shown.sort(key=lambda row: (row.pn.prefix, -row.pn.number))
    return [(str(row.pn), (str(row.pn), row.name, type_name(row.doc_type, types_by_key), row.revision,
                           files_text(row.files), row.state)) for row in shown]


def file_choices(row, revision=None):
    """[(label, vault path)] of one revision's files (default the working one), for Open and Remove File."""
    files = row.files if revision is None else (row.revisions or {}).get(revision, [])
    return [(PurePosixPath(f).name, f) for f in sorted(files)]


def shown_revision(row):
    """The revision a reader of a linked document wants: its latest released one, else its working one."""
    return row.released_revision or row.revision


def link_rows(record, revision, rows_by_number, types_by_key):
    """[(number, values)] for a part's Documents tab: the documents linked to `revision` of `record`."""
    found = []
    for number in record.documents.get(revision, []):
        row = rows_by_number.get(number)
        if row is None:
            found.append((number, (number, "", "", "", "Not found: run Get Latest")))
            continue
        status = "Void" if row.kind == "void" else ("Released" if row.released_revision else "Not released")
        found.append((number, (number, row.name, type_name(row.doc_type, types_by_key), shown_revision(row), status)))
    return found


def linkable(rows, already):
    """The documents a link may be made to: not void, and not linked already (`already`: numbers as text)."""
    return [row for row in rows if row.kind not in ("void", "error") and str(row.pn) not in set(already)]


def link_mode(part_row, revision, may_link_released):
    """How Add... and Remove work on a part's Documents tab for this revision: "checkout" (you have it checked
    out, its working revision), "released" (a released revision: Admins and superusers add at once, removing
    needs sign-offs), or "" with nothing allowed. Returns (mode, why not)."""
    if part_row is None:
        return "", "Click a part first."
    working = revision == part_row.revision
    if part_row.kind == "mine" and working:
        return "checkout", ""
    if part_row.record_status == record_model.STATUS_RELEASED and working:
        return "released", "" if may_link_released else "Only an Admin or a superuser can link a document to a " \
                                                         "released part."
    if working:
        return "", "Check the part out to change its documents."
    return "", "Only the working revision's documents can change."
