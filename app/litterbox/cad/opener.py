"""
opener.py - opens a part's files in the program that should show them.

By default a file opens the way double-clicking it in Explorer would (SolidWorks files open in
SolidWorks, because that is what Windows has registered for them). You can choose a different
program for any file type in your personal settings (C:\\Litterbox\\settings.yaml):

    open_with:
      .pdf: C:\\Program Files\\Adobe\\Acrobat\\Acrobat.exe
      .png: C:\\Program Files\\IrfanView\\i_view64.exe

Nothing here changes a file. Files that are not checked out are read-only on disk, so they
open read-only in the program.
"""

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

from litterbox.core import file_types
from litterbox.cad import cad_programs
from litterbox.errors import LitterboxError


def open_order(files):
    """Order a part's files for opening: the model first, then drawings, then anything else."""
    def rank(path):
        ext = PurePosixPath(path).suffix.lower()
        if ext in file_types.MODEL_EXTENSIONS:
            return 0
        if ext in file_types.DRAWING_EXTENSIONS:
            return 1
        return 2
    return sorted(files, key=lambda path: (rank(path), PurePosixPath(path).name.lower()))


def pick_model(files):
    """The file the Open button opens: the part or assembly (or, failing that, the first file). None if no files."""
    ordered = open_order(files)
    return ordered[0] if ordered else None


def pick_drawing(files):
    """The file the Open Drawing button opens: the part's drawing. None if it has none."""
    drawings = [f for f in open_order(files) if PurePosixPath(f).suffix.lower() in file_types.DRAWING_EXTENSIONS]
    return drawings[0] if drawings else None


def pick_pdf(files):
    """The file Open PDF opens: the PDF made from the part's drawing. None if it has none."""
    pdfs = sorted(f for f in files if PurePosixPath(f).suffix.lower() == file_types.PDF_EXTENSION)
    return pdfs[0] if pdfs else None


def program_for(path, open_with):
    """The program chosen for this file's type in the settings, or None for the Windows default."""
    ext = PurePosixPath(str(path).replace("\\", "/")).suffix.lower()
    if not ext or not isinstance(open_with, dict):
        return None
    for key, program in open_with.items():
        if str(key).strip().lower().lstrip("*") in (ext, ext.lstrip(".")) and program:
            return str(program)
    return None


def open_path(path, open_with=None, startfile=None, popen=None, show_hidden=None):
    """Open one file. Raises LitterboxError with a plain message if it can't be opened.

    `startfile`, `popen` and `show_hidden` are only replaced by the tests.
    """
    path = Path(path)
    if not path.is_file():
        raise LitterboxError(f"{path.name} was not found. Try Get Latest.")
    program = program_for(path, open_with)
    try:
        if program:
            if not Path(program).is_file():
                raise LitterboxError(
                    f"The program set for {path.suffix} files was not found:\n{program}\n\n"
                    "Fix it under open_with in C:\\Litterbox\\settings.yaml.")
            (popen or subprocess.Popen)([program, str(path)])
        elif startfile is not None:
            if path.suffix.lower() in file_types.CAD_EXTENSIONS and show_hidden is not None:
                show_hidden()
            startfile(str(path))
        elif hasattr(os, "startfile"):
            if path.suffix.lower() in file_types.CAD_EXTENSIONS:
                (show_hidden or (lambda: cad_programs.before_opening(path)))()
            os.startfile(str(path))                                    # Windows
        else:
            (popen or subprocess.Popen)(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
    except OSError as e:
        raise LitterboxError(f"Could not open {path.name}: {e}") from e