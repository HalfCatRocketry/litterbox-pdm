"""
file_types.py - the kinds of CAD file Litterbox knows, by extension (lower case, with the dot).

One place for these, so a second CAD program means adding its extensions here, not hunting through the code.
"""

from pathlib import PurePosixPath

PART_EXTENSION = ".sldprt"
ASSEMBLY_EXTENSION = ".sldasm"
DRAWING_EXTENSION = ".slddrw"

MODEL_EXTENSIONS = (PART_EXTENSION, ASSEMBLY_EXTENSION)         # the part or assembly itself
ASSEMBLY_EXTENSIONS = (ASSEMBLY_EXTENSION,)
DRAWING_EXTENSIONS = (DRAWING_EXTENSION,)
SOLIDWORKS_EXTENSIONS = MODEL_EXTENSIONS + DRAWING_EXTENSIONS


def extension(path):
    """'cad/HCR-00042-001_A.SLDPRT' -> '.sldprt'. Works on both kinds of slash."""
    return PurePosixPath(str(path).replace("\\", "/")).suffix.lower()


def file_name(path):
    """'cad/HCR-00042-001_A.SLDPRT' -> 'HCR-00042-001_A.SLDPRT'. Works on both kinds of slash."""
    return PurePosixPath(str(path).replace("\\", "/")).name
