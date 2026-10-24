"""
configuration_naming.py - naming a model's only configuration after the part (core/configuration_names.py): at
Check In and Save Progress with SolidWorks open, before the change is read, so the renamed file goes up with the
check-in (and a part whose Name changed gets its configuration renamed too); and after an import copies files in.

    namer = configuration_naming.make_namer(log=...)
    new_name = namer(repo, record, files)        # the name given, or None (nothing to do, or it couldn't)

A file the person has open with unsaved changes isn't touched (the backend refuses): it is renamed at a later
check-in. Without SolidWorks open nothing is renamed.
"""

import os

from litterbox.cad import cad_programs
from litterbox.core import configuration_names
from litterbox.records import record_configurations
from litterbox.references import reference_reader


def name_file(backend, full_path, part_name, named_before=""):
    """Rename the file's configuration after the part if it should be: the new name, or None."""
    read = getattr(backend, "configurations", None)
    if read is None:
        return None
    own = [c["name"] for c in read(full_path).get("own") or []]
    change = configuration_names.rename(own, named_before, part_name)
    if change is None:
        return None
    backend.name_configuration(full_path, *change)
    return change[1]


def make_namer(backend=None, log=None):
    """namer(repo, record, files) for checkin.checkin(configuration_namer=...): `files` are the revision's CAD files
    (relative to the vault). Without a backend it uses a SolidWorks that is already running, never starting one. Any
    failure is logged and gives None: the check-in goes ahead."""
    log = log or (lambda text: None)

    def namer(repo, record, files):
        if record.is_document or not record.uses_cad or record.cots:
            return None
        known = record_configurations.names(record)
        if known and configuration_names.rename(known, record_configurations.named(record), record.name) is None:
            return None                                 # as last read, nothing to rename: don't open the file
        rel = reference_reader.model_file(repo, record.pn, record.revision, files)
        if rel is None or not os.path.exists(os.path.join(str(repo), rel)):
            return None
        mine = None
        try:
            with cad_programs.session():
                use = backend
                if use is None:
                    use = mine = cad_programs.Backends(attach_only=True)
                try:
                    new = name_file(use, os.path.join(str(repo), rel), record.name,
                                    record_configurations.named(record))
                finally:
                    if mine is not None:
                        mine.close()
        except Exception as e:
            log(f"NOTE: the configuration of {record.pn} wasn't named after it this time ({e}). It will be at a "
                "later check-in with SolidWorks open.")
            return None
        if new:
            log(f"Named the configuration of {record.pn} after it: {new}")
        return new

    return namer
