"""
part_files_export.py - Export Files: copy parts' files out of the vault to a folder, for example to send to a
vendor. The model, drawing, STEP, PDF and saved BOM (HCR-00042-001_A_BOM.csv, parts/release_bom.py) of a chosen
revision (the released one by default), of one part or many, and if asked of every part revision an assembly uses.

The copies are ordinary files (not read-only, not Git LFS pointers), named as in the vault. Nothing in the vault
changes, so nothing goes in a part's history. Files not downloaded yet are downloaded first.
"""

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.exporting import export_folder
from litterbox.git import lfs_download
from litterbox.parts import downloads
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store

MODEL, DRAWING, STEP, PDF, BOM = "model", "drawing", "step", "pdf", "bom"
KINDS = (MODEL, DRAWING, STEP, PDF, BOM)
KIND_LABEL = {MODEL: "Model (part or assembly)", DRAWING: "Drawing", STEP: "STEP", PDF: "PDF",
              BOM: "BOM saved at release (.csv)"}
RELEASED, WORKING = "released", "working"


def kind_of(rel):
    """Which kind of file this is (MODEL, DRAWING, STEP, PDF, BOM), or None for any other."""
    ext = file_types.extension(rel)
    if ext == file_types.BOM_EXTENSION and file_types.file_name(rel).rsplit(".", 1)[0].upper().endswith(
            filenames.BOM_SUFFIX):
        return BOM
    if ext in file_types.MODEL_EXTENSIONS:
        return MODEL
    if ext in file_types.DRAWING_EXTENSIONS:
        return DRAWING
    if ext in file_types.STEP_EXTENSIONS:
        return STEP
    if ext == file_types.PDF_EXTENSION:
        return PDF
    return None


def revision_for(record, which):
    """The revision to export: the latest released one (or the working one if it was never released), the
    working one, or the revision letter `which` names."""
    if which == RELEASED and record.released_revision:
        return record.released_revision
    if which in (RELEASED, WORKING):
        return record.revision
    return which


@dataclass
class ExportPlan:
    files: list = field(default_factory=list)       # vault paths to copy ('cad/HCR-00042-001_A.STEP')
    revisions: dict = field(default_factory=dict)   # PN -> the revision chosen for it
    notes: list = field(default_factory=list)       # things to tell the person (never released, no files of a kind)


def plan(repo, pns, kinds, which=RELEASED, with_used=False):
    """Which files an export of these parts copies. `kinds` is a selection of KINDS; `which` is RELEASED, WORKING
    or a revision letter. With with_used, an assembly brings the part revisions it uses (and what they use, and
    so on), of the same kinds."""
    kinds = set(kinds)
    if not kinds:
        raise export_folder.ExportError("Choose at least one kind of file to export.")
    index = record_files.cad_index(repo)
    result, wanted = ExportPlan(), []
    for pn in pns:
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            raise LitterboxError(str(e)) from e
        rev = revision_for(record, which)
        result.revisions[pn] = rev
        if which == RELEASED and not record.released_revision:
            result.notes.append(f"{pn} has never been released, so its working Rev {rev} is exported.")
        files = downloads.files_to_open(repo, pn, rev) if with_used else index.get(pn, {}).get(rev, [])
        chosen = [rel for rel in files if kind_of(rel) in kinds]
        if not chosen:
            result.notes.append(f"{pn} Rev {rev} has no files of the kinds chosen.")
        wanted += chosen
    result.files = sorted(set(wanted))
    return result


def already_there(files, folder):
    """The file names that the folder has already."""
    return [file_types.file_name(rel) for rel in files if (Path(folder) / file_types.file_name(rel)).exists()]


def export(repo, files, folder, litterbox_root, replace=False):
    """Copy the files to the folder (checked with export_folder.check). Downloads any that are not downloaded
    first. Refuses to replace files the folder has unless `replace`. Returns the names copied."""
    folder = export_folder.check(folder, litterbox_root)
    if not files:
        raise export_folder.ExportError("There are no files to export.")
    clash = already_there(files, folder)
    if clash and not replace:
        raise export_folder.ExportError(f"{folder} already has {len(clash)} of these files ({', '.join(clash[:3])}"
                                        + (", ..." if len(clash) > 3 else "") + ").")
    missing = [rel for rel in files if not (Path(repo) / rel).is_file()]
    if missing:
        raise export_folder.ExportError(f"{missing[0]} is not in your copy of the vault. Try Get Latest first.")
    downloads.download_files(repo, files, "files to export")
    if lfs_download.stubs(repo, files):
        raise export_folder.ExportError("Some files could not be downloaded, so nothing was exported.")
    copied = []
    for rel in files:
        target = folder / file_types.file_name(rel)
        if target.exists():
            os.chmod(target, stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
        shutil.copyfile(Path(repo) / rel, target)       # the contents only: the copy is an ordinary, writable file
        copied.append(target.name)
    return copied
