"""
reference_reader.py - reading which parts an assembly file uses, through SolidWorks. Check-in calls
make_reader's reader for every assembly that changed.
"""

import os

from litterbox.cad import file_types
from litterbox.cad.solidworks import com
from litterbox.core import filenames
from litterbox.records import record_files
from litterbox.references import reference_model


def new_backend(attach_only=False):
    from litterbox.cad.solidworks import sw_backend
    return sw_backend.SolidWorksBackend(attach_only=attach_only)


def read_assembly_references(repo, pn, revision, backend, files=None):
    """The Litterbox parts that this revision's assembly files use, as a sorted list like
    ['HCR-00005-001_A']. Parts are not assemblies, so a revision with no .SLDASM gives [].
    Files that are not Litterbox files (a screw from a library, say) are ignored."""
    own = filenames.file_stem(pn, revision)
    found = set()
    for rel in files if files is not None else record_files.cad_files(repo, pn, revision):
        if file_types.extension(rel) not in file_types.ASSEMBLY_EXTENSIONS:
            continue
        for stored, located in backend.references(os.path.join(str(repo), rel)):
            stem = reference_model.stem_of_path(stored) or reference_model.stem_of_path(located)
            if stem and stem.lower() != own.lower():
                found.add(stem)
    return sorted(found, key=str.lower)


def make_reader(backend=None, log=None):
    """A function to hand to checkin.checkin(): reads an assembly's references when its files changed.

    reader(repo, pn, revision, changed_files) -> list of stems, or None (nothing to update)
    A SolidWorks that can't be reached gives a warning and None: the check-in still goes ahead.
    Without a backend it attaches to a SolidWorks that is already running and never starts one; if
    none is running the references are simply not updated this time.
    """
    log = log or (lambda text: None)

    def reader(repo, pn, revision, changed_files):
        if not any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS for f in changed_files):
            return None
        mine = None
        try:
            with com.com_thread():
                use = backend
                if use is None:
                    use = mine = new_backend(attach_only=True)
                try:
                    return read_assembly_references(repo, pn, revision, use)
                finally:
                    if mine is not None:
                        mine.close()
        except Exception as e:
            log(f"WARNING: could not read what {pn} uses, so its references were not updated. {e}")
            return None

    return reader
