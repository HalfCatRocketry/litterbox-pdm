"""
release_bom.py - the BOM kept with a released assembly revision: HCR-00042-001_A_BOM.csv in the cad folder, beside the
model, written straight after the release and uploaded in a commit of its own. The BOM tab works the BOM out afresh
each time (with the parts' latest names and purchasing info); this file is the fixed record of what the released
revision was made of, as it stood at release.

It is the indented BOM with quantities and costs, the same table Export... writes (exporting/bom_csv.py). Revise
copies only SolidWorks files, so the .CSV stays with the revision it was made for, like the STEP and PDF. Every
released revision with a BOM gets one: a CAD assembly's, and a non-CAD kit's (since 0.6.3; its only file in the cad
folder). A BOM needs no SolidWorks, so it is always made.

The release flags it (records/record_exports.bom_flagged), and saving it clears the flag, so a BOM that couldn't be
saved (the upload failed) shows as "BOM file needs saving" until someone saves it: Part > Save Released BOM
(save(..., later=True)). That BOM is worked out when it is saved, with the parts' names and prices as they are then,
so a BOM saved with its release is never made again over it.
"""

from pathlib import Path

from litterbox import layout
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.exporting import bom_csv
from litterbox.parts import batch_core
from litterbox.records import record_exports
from litterbox.records import record_files
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
    """True for an assembly or kit whose working revision is released and has a BOM (the revision a BOM is kept
    for)."""
    return (not record.is_document and record.status == record_model.STATUS_RELEASED
            and record.revision == record.released_revision
            and bool(reference_model.stems_of(record, record.revision)))


def later_problem(repo, record):
    """Why Save Released BOM won't save this part's BOM, or "" if it will: it must be a released assembly or kit,
    and its BOM not saved with its release already (unless the release flagged it as still needed)."""
    if not wanted(record):
        if record.is_document or not reference_model.stems_of(record, record.revision):
            return "It has no BOM: it isn't an assembly or a kit."
        return "Only a released revision keeps a saved BOM."
    if not record_exports.bom_flagged(record) and \
            bom_path(record.pn, record.revision) in record_files.cad_files(repo, record.pn, record.revision):
        return f"Rev {record.revision}'s BOM was saved with its release already."
    return ""


def save(repo, pns, later=False):
    """Write and upload the BOM of each of these parts that `wanted` says should have one, in one commit.
    Returns (done, failed): [(pn, vault path)] and [(pn, why)]. later=True is Save Released BOM: parts that can't
    have one saved now (later_problem) are in `failed` with why; otherwise they are left out quietly."""
    todo, failed = [], []
    for pn in pns:
        try:
            record = record_store.load(repo, pn)
        except (record_model.RegistryError, LitterboxError) as e:
            if later:
                failed.append((pn, str(e)))
            continue
        why = later_problem(repo, record) if later else ("" if wanted(record) else "-")
        if not why:
            todo.append(pn)
        elif later:
            failed.append((pn, why))
    if not todo:
        return [], failed
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
        record_exports.bom_saved(record, record.revision)
        record_lifecycle.add_event(record, record_model.EVENT_FILES_MADE, user, revision=record.revision,
                                   files=[written[record.pn]])

    message = "BOM saved" if later else "BOM saved with the release"
    batch = batch_core.edit_records(repo, [(pn, PERMISSION, edit, f"{pn}: {message}") for pn in todo],
                                    prepare=prepare)
    done = [(pn, written[pn]) for pn in todo if pn in batch.results]
    failed += [(pn, str(batch.errors[pn])) for pn in todo if pn in batch.errors]
    return done, failed
