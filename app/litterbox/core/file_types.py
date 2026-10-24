"""
file_types.py - the kinds of file Litterbox knows, by extension (lower case, with the dot): each CAD program's parts,
assemblies and drawings, and the files Litterbox makes from them.

One place for these, below everything else, so the records, the parts list and every feature agree on what a file
is. A second CAD program adds its extensions to PROGRAMS here, and the rest of it under cad/<program>/ (see
cad/cad_program.py and cad/cad_programs.py, which picks the program for a file by its extension).
"""

from pathlib import PurePosixPath

PART, ASSEMBLY, DRAWING = "part", "assembly", "drawing"

# {program name: {PART / ASSEMBLY / DRAWING: (extension, ...)}}. A program's name is the one people know it by.
PROGRAMS = {
    "SolidWorks": {PART: (".sldprt",), ASSEMBLY: (".sldasm",), DRAWING: (".slddrw",)},
}


def _every(kind):
    return tuple(ext for kinds in PROGRAMS.values() for ext in kinds.get(kind, ()))


# Each program's templates, by the kind of file made from them: a new part, assembly or drawing starts as a copy of
# one (core/template_rules.py, vault/template_store.py).
TEMPLATES = {
    "SolidWorks": {PART: ".prtdot", ASSEMBLY: ".asmdot", DRAWING: ".drwdot"},
}
TEMPLATE_EXTENSIONS = tuple(ext for kinds in TEMPLATES.values() for ext in kinds.values())

PART_EXTENSIONS = _every(PART)
ASSEMBLY_EXTENSIONS = _every(ASSEMBLY)
DRAWING_EXTENSIONS = _every(DRAWING)
MODEL_EXTENSIONS = PART_EXTENSIONS + ASSEMBLY_EXTENSIONS          # the part or assembly itself
CAD_EXTENSIONS = MODEL_EXTENSIONS + DRAWING_EXTENSIONS            # every file a CAD program opens and copies

# Exports: files made from a part's own CAD files and kept with that revision, under the same name
# (HCR-00042-001_A.STEP from HCR-00042-001_A.SLDPRT, HCR-00042-001_A.PDF from HCR-00042-001_A.SLDDRW).
# They are copied as plain files (never through a CAD program) and stay behind when the part is revised. A released
# assembly revision also keeps its BOM as HCR-00042-001_A_BOM.csv (parts/release_bom.py).
STEP_EXTENSIONS = (".step", ".stp")
PDF_EXTENSION = ".pdf"
BOM_EXTENSION = ".csv"


def extension(path):
    """'cad/HCR-00042-001_A.SLDPRT' -> '.sldprt'. Works on both kinds of slash."""
    return PurePosixPath(str(path).replace("\\", "/")).suffix.lower()


def file_name(path):
    """'cad/HCR-00042-001_A.SLDPRT' -> 'HCR-00042-001_A.SLDPRT'. Works on both kinds of slash."""
    return PurePosixPath(str(path).replace("\\", "/")).name


def kind_of(path):
    """PART, ASSEMBLY or DRAWING for a CAD file; None for any other file."""
    ext = extension(path)
    for kinds in PROGRAMS.values():
        for kind, extensions in kinds.items():
            if ext in extensions:
                return kind
    return None


def program_of(path):
    """The name of the CAD program whose file this is ('SolidWorks'), or None."""
    ext = extension(path)
    return next((name for name, kinds in PROGRAMS.items() if any(ext in exts for exts in kinds.values())), None)


def template_kind(path):
    """PART, ASSEMBLY or DRAWING for a template (what is made from it: 'Bracket.prtdot' -> PART); None for any other
    file."""
    ext = extension(path)
    return next((kind for kinds in TEMPLATES.values() for kind, template in kinds.items() if template == ext), None)


def template_program(path):
    """The name of the CAD program whose template this is ('SolidWorks'), or None."""
    ext = extension(path)
    return next((name for name, kinds in TEMPLATES.items() if ext in kinds.values()), None)


def made_from(template):
    """The extension of a file made from this template ('.drwdot' -> '.slddrw'); '' for a file that isn't one."""
    program, kind = template_program(template), template_kind(template)
    return PROGRAMS[program][kind][0] if program and kind else ""


def is_part(path):
    return extension(path) in PART_EXTENSIONS


def is_assembly(path):
    return extension(path) in ASSEMBLY_EXTENSIONS


def is_drawing(path):
    return extension(path) in DRAWING_EXTENSIONS


def is_model(path):
    return extension(path) in MODEL_EXTENSIONS


def is_cad(path):
    return extension(path) in CAD_EXTENSIONS
