"""
open_actions.py - Open, Open Drawing, Open PDF, opening an older revision, a part's Details and History, and ECOs.
"""

from pathlib import Path, PurePosixPath
from tkinter import messagebox

from litterbox.cad import opener
from litterbox.change_orders import eco_store
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.gui.dialogs import revision_picker
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import download_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import opening_text
from litterbox.gui.windows import eco_view_window
from litterbox.gui.windows import history_window
from litterbox.parts import downloads
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config


class OpenActions:
    """Open, Open Drawing, Open PDF, an older revision, Details/History and ECOs. (a part of the main window, App)."""

    def open_part(self, drawing=False):
        """Open the part's model, or (drawing=True) its drawing, in the program for that file type.

        If the part has both a released and a working revision, ask which one."""
        plan = self._plan("open_drawing" if drawing else "open")
        if not plan:
            return
        pn = plan.targets[0]
        row = self.rows_by_pn[pn]
        waiting = self.jobs.pending_parts().get(str(pn))
        if waiting and not messagebox.askokcancel(
                "Still being uploaded", checkin_text.open_while_busy_text(pn, waiting), parent=self):
            return
        problem = opening_text.open_message(row, drawing)
        if problem:
            self._say(problem, "warn")
            return
        choices = opening_text.open_choices(row, drawing)
        if len(choices) == 1:
            rev = choices[0][0]
        else:
            rev = revision_picker.RevisionPickerDialog(self, pn, [(history_text.revision_label(row, r), r) for r, _f in choices],
                                       "Open drawing of" if drawing else "Open").show()
            if rev is None:
                return
        if not drawing and self._offer_reference_review(pn, row, rev):
            return
        self._open_revision(pn, rev, drawing)

    def _open_revision(self, pn, rev, drawing=False):
        """Open one revision's model or drawing (used by the Open buttons and the History window)."""
        row = self.rows_by_pn.get(pn)
        files = history_text.row_revisions(row).get(rev, []) if row else []
        path = opener.pick_drawing(files) if drawing else opener.pick_model(files)
        if path is None:
            self._say(f"{pn.short} Rev {rev} has no {'drawing' if drawing else 'file'}.", "warn")
            return
        repo = self.repo()
        try:
            missing = lfs_download.stubs(repo, downloads.files_to_open(repo, pn, rev))
        except LitterboxError:
            missing = []
        if missing:                                 # download on demand: fetch the files first, then open
            self.run_task(lambda: downloads.download_for_open(repo, pn, rev),
                          download_text.downloaded_for_open(pn, rev, len(missing)),
                          on_success=lambda _done: self._open_path(path), refresh=True,
                          label=download_text.downloading_label(pn, len(missing)), parts=[pn])
            return
        self._open_path(path)

    def _open_path(self, path):
        try:
            opener.open_path(Path(self.repo()) / path, self.settings.get("open_with"))
        except LitterboxError as e:
            messagebox.showwarning("Can't open", str(e))
            return
        self._say(f"Opening {PurePosixPath(path).name}...")

    def open_drawing(self):
        self.open_part(drawing=True)

    def open_pdf(self):
        """Open a part's PDF (made from its drawing). With PDFs in more than one revision, ask which."""
        plan = self._plan("open_pdf")
        if not plan:
            return
        pn = plan.targets[0]
        row = self.rows_by_pn[pn]
        problem = opening_text.pdf_message(row)
        if problem:
            self._say(problem, "warn")
            return
        choices = opening_text.pdf_choices(row)
        if len(choices) == 1:
            rev = choices[0][0]
        else:
            rev = revision_picker.RevisionPickerDialog(
                self, pn, [(history_text.revision_label(row, r), r) for r, _f in choices], "Open PDF of").show()
            if rev is None:
                return
        self._open_pdf_revision(pn, rev)

    def _open_pdf_revision(self, pn, rev):
        """Open one revision's PDF (Open PDF, and the Review window of My Tasks)."""
        row = self.rows_by_pn.get(pn)
        files = history_text.row_revisions(row).get(rev, []) if row else []
        path = opener.pick_pdf(files)
        if path is None:
            self._say(f"{pn.short} Rev {rev} has no PDF. Part > Generate STEP/PDF... makes one from its drawing.",
                      "warn")
            return
        repo = self.repo()
        if lfs_download.is_stub(repo, path):            # download on demand: just the PDF, not what the model uses
            self.run_task(lambda: downloads.download_files(repo, [path], f"the PDF of {pn} Rev {rev}"), "",
                          on_success=lambda _done: self._open_path(path), refresh=False,
                          label=f"Downloading the PDF of {pn.short}", parts=[pn])
            return
        self._open_path(path)

    def show_history(self, event=None):
        if event is not None and self.tree.identify_column(event.x) == "#0":
            return                                              # double-clicking a tick box isn't asking for history
        chosen = self._selected_pns("open")                    # the highlighted row, or the one selected part
        if len(chosen) != 1:
            self._say("Click one part to see its details and history.", "warn")
            return
        try:
            record = record_store.load(self.repo(), chosen[0])
        except record_model.RegistryError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        pn = chosen[0]
        row = self.rows_by_pn.get(pn)
        if record.is_document:                                  # a window of its own: no Uses, Where used or BOM
            self.show_document_details(record, row)
            return

        def read_bom():
            if window.winfo_exists():
                self._read_bom_into(window.view, pn, window.winfo_exists)

        window = history_window.HistoryWindow(
            self, record, history_text.row_revisions(row) if row else {}, config.currency_or_none(self.repo()),
            on_open=lambda rev, drawing: self._open_revision(pn, rev, drawing), on_view_eco=self.view_eco,
            on_tab=lambda name: self._popout_tab_changed(window, pn, name),
            on_manage_references=lambda: self._load_references(pn), on_bom=lambda rev, mode: read_bom(),
            on_export_bom=lambda rev, mode: self.export_bom(rev, mode, pn),
            on_update_bom=lambda: self.update_bom(pn, then=read_bom),
            on_generate=lambda part: self.generate_step_pdf([part]),
            on_add_bom_item=lambda: self.add_bom_item(pn, then=read_bom),
            on_remove_bom_item=lambda stem: self.remove_bom_item(pn, stem, then=read_bom),
            document_rows=self.document_link_rows, on_open_document=self._open_document_text,
            on_link_document=lambda rev: self.link_document(pn, rev),
            on_unlink_document=lambda rev, number: self.unlink_document(pn, rev, self._doc_number(number)))

    def show_ecos(self):
        """The ECOs screen: every engineering change order in your copy of the vault."""
        self.show_screen("ecos")

    def _view_eco_object(self, eco):
        eco_view_window.EcoViewWindow(self, eco)

    def view_eco(self, number):
        try:
            eco = eco_store.load(self.repo(), number)
        except LitterboxError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        eco_view_window.EcoViewWindow(self, eco)
