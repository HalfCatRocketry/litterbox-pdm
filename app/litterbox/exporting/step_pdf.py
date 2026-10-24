"""
step_pdf.py - Generate STEP/PDF: making the STEP (from the model) and PDF (from the drawing) of parts' working
revisions with SolidWorks, into a folder. The folder is either one outside the vault (nothing in the vault
changes) or the vault's cad folder, which parts/generate_files.py looks after (locks, the record, the upload).

Files are named as in the vault (HCR-00042-001_A.STEP, HCR-00042-001_A.PDF). In the vault, a STEP or PDF the
revision already has is replaced under its own name (an old HCR-00042-001_A.STP stays .STP), so nothing is ever
deleted. SolidWorks writes each file to a temporary folder first, so a failed save never leaves half a file
behind, and it then replaces any file of that name. STEP files are always AP214, and a PDF has every sheet (cad/solidworks/sw_saving.py).
"""

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox.cad import cad_programs
from litterbox.cad.cad_errors import CadError
from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.parts import downloads
from litterbox.records import record_exports
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.workflows import workflow_request

STEP, PDF = record_exports.STEP, record_exports.PDF
EXTENSION = {STEP: "STEP", PDF: "PDF"}


def source_of(kind, files):
    """The file a STEP (the model) or PDF (the drawing) is made from, out of a revision's files, or None."""
    wanted = file_types.MODEL_EXTENSIONS if kind == STEP else file_types.DRAWING_EXTENSIONS
    return next((f for f in sorted(files) if file_types.extension(f) in wanted), None)


def possible_kinds(files):
    """Which of STEP and PDF a revision with these files can have: a STEP needs a model, a PDF a drawing."""
    return [kind for kind in record_exports.KINDS if source_of(kind, files)]


def existing(kind, files):
    """The revision's STEP (.STEP or .STP) or PDF files among its files."""
    wanted = file_types.STEP_EXTENSIONS if kind == STEP else (file_types.PDF_EXTENSION,)
    return [f for f in sorted(files) if file_types.extension(f) in wanted]


def target_name(pn, revision, kind):
    """'HCR-00042-001_A.STEP' or 'HCR-00042-001_A.PDF'."""
    return filenames.filename(pn, revision, EXTENSION[kind])


def vault_name(pn, revision, kind, files):
    """The name to make a kind under in the vault: the revision's own file of that kind if it has one (the one
    with Litterbox's spelling first), else target_name()."""
    there = existing(kind, files)
    usual = target_name(pn, revision, kind)
    if not there:
        return usual
    names = [file_types.file_name(rel) for rel in there]
    return next((name for name in names if name.upper() == usual.upper()), names[0])


@dataclass
class Job:
    """What to make for one part: its working revision, the kinds asked for that its files allow, the file each
    is made from and the name each gets."""
    pn: object
    revision: str
    kinds: list
    sources: dict                                    # kind -> vault path of the model or drawing
    names: dict = field(default_factory=dict)        # kind -> the file name to make
    possible: list = field(default_factory=list)     # the kinds its files allow


@dataclass
class Made:
    made: dict = field(default_factory=dict)        # PN -> {kind: {"file": name, "from": {...}, "solidworks": ...}}
    errors: dict = field(default_factory=dict)      # PN -> why nothing (or not everything) was made
    solidworks: str = ""


def jobs_for(repo, pns, kinds, in_vault=False):
    """(jobs, notes) for making `kinds` of these parts' working revisions. A part that can't have any of them is
    left out with a note saying why. `in_vault`: name them to replace the revision's own STEP and PDF."""
    kinds = [kind for kind in record_exports.KINDS if kind in set(kinds)]
    if not kinds:
        raise LitterboxError("Choose STEP, PDF or both.")
    index = record_files.cad_index(repo)
    jobs, notes = [], []
    for pn in pns:
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            notes.append(str(e))
            continue
        if record.status == record_model.STATUS_VOID:
            notes.append(f"{pn} is void.")
            continue
        files = index.get(pn, {}).get(record.revision, [])
        possible = possible_kinds(files)
        chosen = [kind for kind in kinds if kind in possible]
        if PDF in kinds and PDF not in possible and chosen:
            notes.append(f"{pn} Rev {record.revision} has no drawing, so it gets no PDF.")
        if not chosen:
            notes.append(f"{pn} Rev {record.revision} has no " + (
                "model or drawing." if len(kinds) == 2 else "model." if kinds == [STEP] else "drawing."))
            continue
        names = {kind: vault_name(pn, record.revision, kind, files) if in_vault else
                 target_name(pn, record.revision, kind) for kind in chosen}
        jobs.append(Job(pn, record.revision, chosen, {kind: source_of(kind, files) for kind in chosen}, names,
                        possible))
    return jobs, notes


def make(repo, jobs, folder, backend_factory=None, log=diagnostics.LOG):
    """Make every job's files in `folder`, replacing files of the same name. Downloads what SolidWorks needs to
    open them first (an assembly needs its parts). A part that fails is reported in Made.errors and the rest carry
    on. With no backend_factory, each file's own CAD program is used (cad/cad_programs.py), and Litterbox closes it
    again if it started it."""
    result = Made()
    if not jobs:
        return result
    if backend_factory is None:
        sources = [source for job in jobs for source in job.sources.values()]
        for program in cad_programs.for_files(sources):
            if not program.installed():
                raise CadError(f"{program.name} is not installed on this computer, so it can't make STEP or PDF "
                               "files.")
        backend_factory = cad_programs.Backends
    needed = sorted({rel for job in jobs for rel in _to_open(repo, job)})
    downloads.download_files(repo, needed, "files to make STEP and PDF files from")
    missing = set(lfs_download.stubs(repo, needed))
    folder = Path(folder)
    work = Path(tempfile.mkdtemp(prefix="litterbox-step-pdf-"))
    try:
        with cad_programs.session():
            backend = backend_factory()
            try:
                for job in jobs:
                    _make_one(repo, job, folder, work, backend, missing, result, log)
            finally:
                backend.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result


def _to_open(repo, job):
    """The CAD files the CAD program needs to open the job's part (not the STEP and PDF files it already has)."""
    return [rel for rel in downloads.files_to_open(repo, job.pn, job.revision)
            if file_types.extension(rel) in file_types.CAD_EXTENSIONS]


def _make_one(repo, job, folder, work, backend, missing, result, log):
    sources = list(job.sources.values())
    not_there = [rel for rel in _to_open(repo, job) if rel in missing]
    if not_there:
        result.errors[job.pn] = f"{not_there[0]} could not be downloaded."
        return
    try:
        hashes = workflow_request.file_hashes(repo, sources)
    except LitterboxError as e:
        result.errors[job.pn] = str(e)
        return
    for kind in job.kinds:
        name = job.names[kind]
        made_at = work / name
        source = str(Path(repo) / job.sources[kind])
        try:
            if kind == STEP:
                backend.save_step(source, str(made_at))
            else:
                backend.save_pdf(source, str(made_at))
            if not result.solidworks:
                result.solidworks = backend.version()
            target = folder / name
            if target.exists():
                os.chmod(target, stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            shutil.copyfile(made_at, target)
        except (LitterboxError, OSError) as e:
            result.errors[job.pn] = f"{record_exports.LABEL[kind]}: {e}"
            continue
        except Exception as e:                      # anything SolidWorks raises over COM
            log(f"SolidWorks failed making {name}: {e!r}")
            result.errors[job.pn] = f"SolidWorks could not make {name}: {e}"
            continue
        log(f"Made {name} from {job.sources[kind]}")
        result.made.setdefault(job.pn, {})[kind] = {"file": name, "from": {job.sources[kind]: hashes[job.sources[kind]]},
                                                    "solidworks": result.solidworks}
