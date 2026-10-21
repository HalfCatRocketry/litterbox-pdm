"""
export_actions.py - Export Files (copy parts' files to a folder outside the vault) and Export BOM (the BOM tab's
Export... button). Neither changes the vault. See exporting/.
"""

from pathlib import Path
from tkinter import filedialog, messagebox

from litterbox.cad import file_types
from litterbox.errors import LitterboxError
from litterbox.exporting import bom_csv
from litterbox.exporting import export_folder
from litterbox.exporting import part_files_export
from litterbox.gui.dialogs import export_files_dialog
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import export_text
from litterbox.references import bom
from litterbox.references import reference_model
from litterbox.user import settings


class ExportActions:
    """Export Files and Export BOM. (a part of the main window, App)."""

    def _remember_export_folder(self, folder):
        if self.settings.get(export_text.SETTING) != str(folder):
            self.settings[export_text.SETTING] = str(folder)
            try:
                settings.save(self.settings)
            except OSError:
                pass                                    # only a convenience

    def export_files(self):
        plan = self._plan("export_files")
        if not plan:
            return
        pns, repo = plan.targets, self.repo()
        has_assembly = any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS
                           for pn in pns for files in self.rows_by_pn[pn].revisions.values() for f in files)
        title = str(pns[0]) if len(pns) == 1 else f"{len(pns)} parts"
        answer = export_files_dialog.ExportFilesDialog(self, title, export_text.start_folder(self.settings),
                                                       settings.ROOT, has_assembly).show()
        if answer is None:
            return
        try:
            chosen = part_files_export.plan(repo, pns, answer["kinds"], answer["which"], answer["with_used"])
        except LitterboxError as e:
            messagebox.showwarning("Export Files", str(e), parent=self)
            return
        if not chosen.files:
            messagebox.showwarning("Export Files", "\n".join(export_text.plan_lines(chosen)), parent=self)
            return
        folder = answer["folder"]
        clash = part_files_export.already_there(chosen.files, folder)
        if clash and not messagebox.askyesno("Export Files", export_text.replace_question(folder, clash), parent=self):
            return
        self._remember_export_folder(folder)
        notes = " ".join(chosen.notes)
        self.run_task(lambda: part_files_export.export(repo, chosen.files, folder, settings.ROOT, replace=True),
                      "", on_success=lambda names: self._say(export_text.exported_text(folder, names)
                                                             + (f" {notes}" if notes else "")),
                      refresh=False, label="Exporting files")

    def export_bom(self, rev, mode, pn=None):
        """The BOM tab's Export...: write the BOM of the part shown (`pn`, or the details pane's), as it is picked on
        the tab, to a .csv file."""
        pn = pn or getattr(self, "pane_pn", None)
        if pn is None or not rev:
            return
        start = Path(export_text.start_folder(self.settings))
        path = filedialog.asksaveasfilename(parent=self, title="Export BOM", initialdir=str(start),
                                            initialfile=bom_csv.default_name(pn, rev, mode),
                                            defaultextension=".csv", filetypes=[("Spreadsheet (CSV)", "*.csv")])
        if not path:
            return
        try:
            export_folder.check(Path(path).parent, settings.ROOT)
        except export_folder.ExportError as e:
            messagebox.showwarning("Export BOM", str(e), parent=self)
            return
        self._remember_export_folder(Path(path).parent)
        repo = self.repo()

        def work():
            found = bom.lines(reference_model.load_records(repo), pn, rev, mode)
            return bom_csv.write(path, found, settings.ROOT), len(found)

        self.run_task(work, "", on_success=lambda result: self._say(bom_text.exported_text(*result)),
                      refresh=False, label="Exporting the BOM")
