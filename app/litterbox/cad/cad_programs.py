"""
cad_programs.py - the CAD programs Litterbox knows (cad/cad_program.py), and the one place the rest of Litterbox
reaches them: the program for a file (by its extension, core/file_types.py), a session to use them in, and a backend
that hands each call to the program whose file it is.

    with cad_programs.session():                # every program's thread setup (SolidWorks: COM)
        backends = cad_programs.Backends()      # a backend per program, each made when first needed
        backends.references(path)               # by the file's program
        backends.close()

A new program: its extensions in core/file_types.py, its code under cad/<program>/ with a CadProgram, and that
program in PROGRAMS here. Nothing outside cad/ imports a program's own modules (tests/architecture checks it).
"""

import contextlib

from litterbox.cad.cad_errors import CadError
from litterbox.cad.solidworks import sw_program
from litterbox.core import file_types

PROGRAMS = (sw_program.SOLIDWORKS,)

# The program used when there is no file to choose by: the importer's scan, the version in the log.
DEFAULT = sw_program.SOLIDWORKS


def for_file(path):
    """The CadProgram whose file this is, or None."""
    name = file_types.program_of(path)
    return next((program for program in PROGRAMS if program.name == name), None)


def for_files(paths):
    """The programs of these files, each once, in the order first met."""
    found = []
    for path in paths:
        program = for_file(path)
        if program is not None and program not in found:
            found.append(program)
    return found


def installed(path=None):
    """Can Litterbox start the program for this file (or the DEFAULT one) on this computer?"""
    program = for_file(path) if path is not None else DEFAULT
    return program is not None and program.installed()


@contextlib.contextmanager
def session(programs=None):
    """Every program's (or these programs') thread setup, for the thread that uses their backends."""
    with contextlib.ExitStack() as stack:
        for program in programs if programs is not None else PROGRAMS:
            stack.enter_context(program.session())
        yield


def before_opening(path):
    """Get ready for Windows to open this file (SolidWorks: show a copy that was left running out of sight)."""
    program = for_file(path)
    if program is not None:
        program.before_opening()


def open_read_only(paths):
    """[OpenDocument] of these full paths that their programs have open read-only; None if none of the programs is
    running."""
    found, running = [], False
    for program in for_files(paths):
        docs = program.open_read_only([path for path in paths if program.owns(path)])
        if docs is not None:
            running = True
            found += docs
    return found if running else None


def make_writable(paths, reload=()):
    """Make these open documents writable in their programs, reloading those in `reload` first: (done, failed)."""
    done, failed = [], []
    for program in for_files(paths):
        mine = [path for path in paths if program.owns(path)]
        program_done, program_failed = program.make_writable(mine, [path for path in reload if program.owns(path)])
        done += program_done
        failed += program_failed
    return done, failed


def watchers(on_change):
    """A watcher (start, stop, snapshot) for every program that can say what the person has open."""
    return [w for w in (program.watcher(on_change) for program in PROGRAMS) if w is not None]


class Backends:
    """A backend for every program, each made when first needed: each call goes to the backend of the program whose
    file it is about (the first path it is given). Behaves like one backend (cad/cad_program.py)."""

    def __init__(self, attach_only=False):
        self.attach_only = attach_only
        self._made = {}                                     # program name: its backend

    def for_program(self, program):
        if program.name not in self._made:
            self._made[program.name] = program.backend(attach_only=self.attach_only)
        return self._made[program.name]

    def for_file(self, path):
        program = for_file(path)
        if program is None:
            raise CadError(f"Litterbox can't open {file_types.file_name(path)}: it isn't a file of a CAD program "
                           "Litterbox knows.")
        return self.for_program(program)

    def references(self, path):
        return self.for_file(path).references(path)

    def components(self, path):
        return self.for_file(path).components(path)

    def library_components(self, path):
        return self.for_file(path).library_components(path)

    def material(self, path):
        return self.for_file(path).material(path)

    def copy(self, src, dst):
        return self.for_file(src).copy(src, dst)

    def repoint(self, file, old, new):
        return self.for_file(file).repoint(file, old, new)

    def save_step(self, path, out):
        return self.for_file(path).save_step(path, out)

    def save_pdf(self, path, out):
        return self.for_file(path).save_pdf(path, out)

    def version(self, path=None):
        """The version of the program for this file, or of the DEFAULT one."""
        return (self.for_file(path) if path is not None else self.for_program(DEFAULT)).version()

    def close(self):
        """Close every backend made, even if one fails (the first failure is raised afterwards)."""
        made, self._made = list(self._made.values()), {}
        error = None
        for backend in made:
            try:
                backend.close()
            except Exception as e:
                error = error or e
        if error is not None:
            raise error
