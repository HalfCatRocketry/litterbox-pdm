"""
release_bom.py - the BOM kept with a released assembly revision: HCR-00042-001_A_BOM.csv in the cad folder, beside the
model, written straight after the release and uploaded in a commit of its own. The BOM tab works the BOM out afresh
each time (with the parts' latest names and purchasing info); this file is the fixed record of what the released
revision was made of, as it stood at release.

It is the indented BOM with quantities and costs, the same table Export... writes (exporting/bom_csv.py). Revise
copies only SolidWorks files, so the .CSV stays with the revision it was made for, like the STEP and PDF. Only CAD
assemblies get one: a non-CAD kit keeps no files in the cad folder. A BOM needs no SolidWorks, so it is always made.
"""

from pathlib import Path

from litterbox import layout
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.exporting import bom_csv
from litterbox.parts import batch_core
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import bom
from litterbox.references import reference_model
from litterbox.vault import config


PERMISSION = "generate_files"           # the same as Generate STEP/PDF: any member


def bom_path(pn, revision):
    """'cad/HCR-00042-001_A_BOM.csv': where a released revision's BOM is kept. The _BOM keeps it clear of any other
    .csv a revision might have (a file a parametric part reads, say)."""
    return f"{layout.CAD_DIR_NAME}/{filenames.bom_filename(pn, revision)}"


def wanted(record):
    """True for a CAD assembly whose working revision is released (the revision a BOM is kept for)."""
    return (record.uses_cad and record.status == record_model.STATUS_RELEASED
            and record.revision == record.released_revision
            and bool(reference_model.stems_of(record, record.revision)))


def save(repo, pns):
    """Write and upload the BOM of each of these parts that `wanted` says should have one, in one commit.
    Returns (done, failed): [(pn, vault path)] and [(pn, why)]."""
    todo = []
    for pn in pns:
        try:
            if wanted(record_store.load(repo, pn)):
                todo.append(pn)
        except (record_model.RegistryError, LitterboxError):
            continue
    if not todo:
        return [], []
    written = {}

    def prepare(_user):                     # after the pull, so the BOM is read from the latest records
        records = reference_model.load_records(repo)
        for pn in todo:
            record = records.get(pn)
            if record is None or not wanted(record):
                continue
            path = bom_path(pn, record.revision)
            bom_csv.write_in_vault(Path(repo) / path, bom.lines(records, pn, record.revision, bom.INDENTED),
                                   bom.cost_summary(records, pn, record.revision), config.currency_or_none(repo))
            written[pn] = path
        return list(written.values())

    def edit(record, user):
        if record.pn not in written:
            raise record_model.RegistryError(f"{record.pn} is no longer a released assembly.")
        record_lifecycle.add_event(record, record_model.EVENT_FILES_MADE, user, revision=record.revision,
                                   files=[written[record.pn]])

    batch = batch_core.edit_records(repo, [(pn, PERMISSION, edit, f"{pn}: BOM saved with the release")
                                           for pn in todo], prepare=prepare)
    done = [(pn, written[pn]) for pn in todo if pn in batch.results]
    failed = [(pn, str(batch.errors[pn])) for pn in todo if pn in batch.errors]
    return done, failed
