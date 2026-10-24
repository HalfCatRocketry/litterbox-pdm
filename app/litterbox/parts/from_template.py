"""
from_template.py - Litterbox making a part's file from one of the vault's templates (core/template_rules.py): its
first model (New Part and New Assembly with a template, or Part > New Model...), or its drawing (Part > New
Drawing...), as an empty sheet. The file is made in the cad folder under the part's name for its working revision
(HCR-00042-001_A.SLDDRW), like a file the person saved there, so it goes up with the part's next check-in. The part
must be checked out to you; the window checks that, and opens the file afterwards.

    template = from_template.default_template(repo, pn, file_types.DRAWING)     # its project's, else the org's
    rel = from_template.make(repo, pn, template.file)                         # "cad/HCR-00042-001_A.SLDDRW"
"""

import posixpath
from pathlib import Path

from litterbox import layout
from litterbox.cad import cad_programs
from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.core import template_rules
from litterbox.errors import LitterboxError
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.vault import config
from litterbox.vault import template_admin
from litterbox.vault import template_store

MODEL_KINDS = (file_types.PART, file_types.ASSEMBLY)


def target(pn, revision, template_file):
    """Where a file made from this template for the part goes: "cad/HCR-00042-001_A.SLDDRW"."""
    return posixpath.join(layout.CAD_DIR_NAME, filenames.filename(pn, revision, file_types.made_from(template_file)))


def problem(record, files, kind):
    """Why this part can't have a new file of this kind (a model: PART or ASSEMBLY; or a DRAWING) made for it now,
    or "" if it can. `files` are its working revision's files."""
    if record.is_document:
        return "Templates are for parts' CAD files, not documents."
    if not record.uses_cad:
        return f"{record.pn} is a non-CAD part: it has no CAD files."
    models = [f for f in files if file_types.is_model(f)]
    drawings = [f for f in files if file_types.is_drawing(f)]
    if kind == file_types.DRAWING:
        if drawings:
            return f"{record.pn} Rev {record.revision} has a drawing already ({file_types.file_name(drawings[0])})."
        if not models:
            return f"{record.pn} Rev {record.revision} has no model yet. Make or save its model first."
        return ""
    if models:
        return f"{record.pn} Rev {record.revision} has a model already ({file_types.file_name(models[0])})."
    return ""


def wanted_kinds(repo, pn):
    """The kinds of file a part could have made now: (PART, ASSEMBLY) with no model yet, (DRAWING,) with a model
    and no drawing, () otherwise."""
    record = record_store.load(repo, batch_core.as_pn(pn))
    files = record_files.cad_files(repo, record.pn, record.revision)
    if not problem(record, files, file_types.PART):
        return MODEL_KINDS
    if not problem(record, files, file_types.DRAWING):
        return (file_types.DRAWING,)
    return ()


def model_kind(repo, pn):
    """ASSEMBLY for a part number in the assemblies' variants (from the org's assembly start), else PART."""
    return file_types.ASSEMBLY if batch_core.as_pn(pn).variant >= config.get_assembly_variant_start(repo) \
        else file_types.PART


def choices(repo, pn, kind):
    """The templates the part may use for a file of this kind, the one it gets first (its project's, else the
    org's: template_rules.choices). For a model (PART or ASSEMBLY), both kinds: the part number's kind first."""
    record = record_store.load(repo, batch_core.as_pn(pn))
    templates = template_store.load(repo)
    if kind == file_types.DRAWING:
        return template_rules.choices(templates, kind, record.project)
    first = model_kind(repo, record.pn)
    other = file_types.PART if first == file_types.ASSEMBLY else file_types.ASSEMBLY
    return (template_rules.choices(templates, first, record.project)
            + template_rules.choices(templates, other, record.project))


def default_template(repo, pn, kind):
    found = choices(repo, pn, kind)
    return found[0] if found else None


@converts_errors
def make(repo, pn, template_file, backend=None, log=print):
    """Make the part's new model or drawing from the vault's template `template_file`, and return its path relative
    to the vault. Raises LitterboxError, with nothing made, if it can't (a model or drawing it has already, a
    template that isn't there or that SolidWorks can't use, SolidWorks newer than the org's)."""
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    template = template_rules.find(template_store.load(repo), template_file)
    if template is None:
        raise LitterboxError(f"{template_file} isn't one of the vault's templates any more.")
    why = problem(record, record_files.cad_files(repo, pn, record.revision), template.kind)
    if why:
        raise LitterboxError(why)
    label = template_rules.LABELS[template.kind].lower()
    permission_check.check_solidworks_version(repo, f"make {pn}'s {label}")
    rel = target(pn, record.revision, template.file)
    template_admin.download(repo, [template])
    owns = backend is None
    with cad_programs.session():
        if owns:
            backend = cad_programs.Backends()
        try:
            backend.new_from_template(str(template_store.path(repo, template)), str(Path(repo) / rel))
        finally:
            if owns:
                backend.close()
    log(f"Made {file_types.file_name(rel)} from the template {template.name}")
    return rel
