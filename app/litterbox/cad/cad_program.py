"""
cad_program.py - what Litterbox needs from a CAD program: the CadProgram every program under cad/<program>/ is, and
the backend it gives. The rest of Litterbox asks cad/cad_programs.py for the program of a file and never imports a
program's own code, so a second program changes nothing outside cad/ but its extensions (core/file_types.py).

A CadProgram (one instance per program, e.g. cad/solidworks/sw_program.SOLIDWORKS):

    name                         as people know it: "SolidWorks"; its extensions are file_types.PROGRAMS[name]
    library_name                 its library of standard parts, as people know it ("Toolbox"); "" if it has none
    installed()                  can Litterbox start it on this computer?
    session()                    a context to use a backend in: on the thread that uses it (SolidWorks: COM)
    backend(attach_only=False)   a Backend (below); attach_only: use one already running, never start one
    before_opening()             called before Windows opens one of its files (SolidWorks shows a hidden copy)
    library_folder()             the folder this computer's copy keeps its library in ("" if unknown or none)
    watcher(on_change)           something with start(), stop() and snapshot() that tells on_change what the
                                 person opens, saves and closes (cad/open_documents.py); None if it can't
    open_read_only(paths)        [OpenDocument] of these that it has open read-only; None if it isn't running
    make_writable(paths, reload) make those open documents writable, reloading those in `reload` from disk first;
                                 (done, failed) as ([path], [(path, why)])

A backend reads and copies files, and makes new ones. None of its calls changes an original file:

    references(path)             [(stored, found)] for the file's direct references: the path the file keeps, and
                                 where the program finds it
    components(path)             [(file, COUNTED / SUPPRESSED / EXCLUDED)] for an assembly's top-level components,
                                 one per copy
    library_components(path)     the files of an assembly's top-level components that come from its library
    material(path)               a part's material ('' for none)
    component_configurations(path)  {file: [configuration names]} of a part each top-level component uses
    configurations(path)         a part's or assembly's configurations: {"own": [{name, id}], "active": name,
                                 "materials": {name: material} (parts), "linked": [outside files it is linked to]}
    name_configuration(path, old, new)  rename a configuration of a file that may be changed, and save it
    copy(src, dst)               copy a file, with its references kept working
    repoint(file, old, new)      change one reference inside the NEW file
    save_step(path, out)         save a part or assembly as a STEP file
    save_pdf(path, out)          save every sheet of a drawing as a PDF
    new_from_template(template, out)  make a new file at `out` from a template (a part, an assembly, or a drawing
                                 as an empty sheet), saved and closed (core/file_types.TEMPLATES)
    version()                    the program's version, for the log and the files' history
    close()                      let go of the program, and shut down one the backend started

This base class is a program that can do none of it, so a program only fills in what it has.
"""

import contextlib

from litterbox.cad.cad_errors import CadError
from litterbox.core import file_types

# What an assembly's component is, for counting (a backend's components())
COUNTED, SUPPRESSED, EXCLUDED = "counted", "suppressed", "excluded"


class CadProgram:
    name = ""
    library_name = ""

    @property
    def extensions(self):
        """Every extension of this program's files."""
        return tuple(ext for exts in file_types.PROGRAMS.get(self.name, {}).values() for ext in exts)

    def owns(self, path):
        return file_types.extension(path) in self.extensions

    def installed(self):
        return False

    def session(self):
        return contextlib.nullcontext()

    def backend(self, attach_only=False):
        raise CadError(f"Litterbox can't use {self.name} on this computer.")

    def before_opening(self):
        pass

    def library_folder(self):
        return ""

    def watcher(self, on_change):
        return None

    def open_read_only(self, paths):
        return None

    def make_writable(self, paths, reload=()):
        return [], [(path, f"Litterbox can't do that in {self.name}") for path in paths]
