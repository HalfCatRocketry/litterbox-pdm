"""
sw_program.py - SolidWorks as a CAD program (cad/cad_program.py): what the rest of Litterbox reaches it through.

    SOLIDWORKS.backend()          sw_backend.SolidWorksBackend: references, counting, materials, copies, STEP and PDF
    SOLIDWORKS.session()          COM switched on for the thread (com.com_thread)
    SOLIDWORKS.watcher(...)       sw_watcher.SolidWorksWatcher: what the person has open
    SOLIDWORKS.library_folder()   the Toolbox folder this computer's SolidWorks uses (sw_process.toolbox_folder)
"""

from litterbox.cad.cad_program import CadProgram
from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_backend
from litterbox.cad.solidworks import sw_process
from litterbox.cad.solidworks import sw_reload
from litterbox.cad.solidworks import sw_watcher


class SolidWorks(CadProgram):
    name = "SolidWorks"
    library_name = "Toolbox"

    def installed(self):
        return sw_process.solidworks_installed()

    def session(self):
        return com.com_thread()

    def backend(self, attach_only=False):
        return sw_backend.SolidWorksBackend(attach_only=attach_only)

    def before_opening(self):
        com.show_hidden_solidworks()

    def library_folder(self):
        return sw_process.toolbox_folder()

    def watcher(self, on_change):
        return sw_watcher.SolidWorksWatcher(on_change=on_change)

    def open_read_only(self, paths):
        return sw_reload.open_read_only(paths)

    def make_writable(self, paths, reload=()):
        return sw_reload.make_writable(paths, reload)


SOLIDWORKS = SolidWorks()
