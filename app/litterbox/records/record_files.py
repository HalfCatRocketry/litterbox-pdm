"""
record_files.py - which CAD files in the cad folder belong to which part and revision (by their
Litterbox names, e.g. HCR-00042-001_A.SLDPRT).
"""

from litterbox import layout
from litterbox.core.filenames import parse_filename
from litterbox.core.part_number import PNError
from litterbox.core.revision_letters import check_revision
from litterbox.records import record_store


def cad_index(repo):
    """Scan the cad folder once. Returns {PN: {revision: [relative paths]}} for every file in it.

    Paths are relative to the repo with forward slashes, which is what git
    wants, for example {'A': ['cad/HCR-00042-001_A.SLDDRW', 'cad/HCR-00042-001_A.SLDPRT']}.
    Files that aren't named like Litterbox files (~$ temp files, notes) are ignored.
    """
    index = {}
    folder = record_store.cad_dir(repo)
    if not folder.is_dir():
        return index
    for path in folder.iterdir():
        if not path.is_file():
            continue
        try:
            file_pn, revision, _ext = parse_filename(path.name)
        except PNError:
            continue
        index.setdefault(file_pn, {}).setdefault(revision, []).append(f"{layout.CAD_DIR_NAME}/{path.name}")
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
