"""
record_files.py - which files belong to which part and revision, by their Litterbox names: CAD files in the cad
folder (HCR-00042-001_A.SLDPRT), and documents' files in the documents folder (PROP-0001_A.docx).
"""

from litterbox import layout
from litterbox.core import doc_number
from litterbox.core.doc_number import DocNumber
from litterbox.core.filenames import parse_filename
from litterbox.core.part_number import PNError
from litterbox.core.revision_letters import check_revision
from litterbox.records import record_store


def folder_name(pn):
    """The folder a number's files live in: 'cad' for a part, 'documents' for a document."""
    return layout.DOC_DIR_NAME if isinstance(pn, DocNumber) else layout.CAD_DIR_NAME


def cad_index(repo):
    """Scan the cad and documents folders once. Returns {number: {revision: [relative paths]}} for every file in
    them, parts by PN and documents by DocNumber.

    Paths are relative to the repo with forward slashes, which is what git
    wants, for example {'A': ['cad/HCR-00042-001_A.SLDDRW', 'cad/HCR-00042-001_A.SLDPRT']}.
    Files that aren't named like Litterbox files (~$ temp files, notes) are ignored.
    """
    index = {}
    for folder_text, parse in ((layout.CAD_DIR_NAME, parse_filename), (layout.DOC_DIR_NAME, doc_number.parse_filename)):
        folder = record_store.cad_dir(repo).parent / folder_text
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file():
                continue
            try:
                number, revision, _ext = parse(path.name)
            except PNError:
                continue
            index.setdefault(number, {}).setdefault(revision, []).append(f"{folder_text}/{path.name}")
    for revisions in index.values():
        for files in revisions.values():
            files.sort()
    return index


def cad_files(repo, pn, revision=None):
    """The CAD files in the cad folder for one revision of a PN (see cad_index).

    Without `revision` it is the part's working (latest) revision, read from its record.
    """
    if revision is None:
        revision = record_store.load(repo, pn).revision
    return cad_index(repo).get(pn, {}).get(check_revision(revision), [])


def all_cad_files(repo, pn):
    """Every CAD file of every revision of a PN, sorted."""
    return sorted(f for files in cad_index(repo).get(pn, {}).values() for f in files)
