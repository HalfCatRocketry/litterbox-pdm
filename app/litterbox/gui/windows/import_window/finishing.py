"""
finishing.py - Finish & Import, cancelling a running step, and closing the Import window.
"""

import tkinter as tk
from tkinter import messagebox

from litterbox.errors import LitterboxError
from litterbox.gui.logic import error_text
from litterbox.gui.logic import import_table
from litterbox.importing import import_errors


class Finishing:
    """Finish & Import, cancelling a running step, and closing the Import window. (part of the Import window)."""

    def _finish(self):
        if self._blocked():
            return
        self._end_edit()
        self.conflicts = []
        if self.cots and not self._cots_confirmed:
            self._check_duplicates(then=self._confirm_cots)       # look for duplicates, then ask
            return
        try:
            self.session.finish(self._after(self._finished), self._progress)
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking the part numbers...", finishing=True)

    def _confirm_cots(self, checked):
        """The last question before Import COTS goes ahead: it names the duplicates found, if any."""
        if not checked:
            return
        entries = self.session.prepared.proposal.entries
        text = import_table.import_cots_confirm_text(len(entries), self.duplicates, [e.name for e in entries])
        if messagebox.askyesno("Import as COTS?", text, parent=self):
            self._cots_confirmed = True
            self._finish()
        else:
            self._say("Nothing was imported.", "warn")

    def _finished(self, result, error):
        confirmed, self._cots_confirmed = self._cots_confirmed, False      # each Finish asks again
        self.session.set_allow_external(False)             # the answer to the question below counts for one try only
        if isinstance(error, import_errors.ExternalReferences):
            self._show("table")
            self._rebuild()
            if messagebox.askyesno("Files outside this import", import_table.import_external_text(error), parent=self):
                self.session.set_allow_external(True)
                self._cots_confirmed = confirmed
                self._finish()
            else:
                self._say("Nothing was imported. Select the missing items, or scan their folder too, and try again.",
                          "warn")
            return
        if error is None:
            messagebox.showinfo("Import complete", import_table.import_result_text(result), parent=self)
            if self.on_imported:
                self.on_imported(result)
            self._really_close()
            return
        self._show("table")
        if isinstance(error, import_errors.PNConflict):
            self.conflicts, self.renumbered = error.conflicts, error.renumbered
            self._rebuild()
            self._say("Nothing was imported: some part numbers can't be used. Change the red rows, then press "
                      "Finish & Import again.", "error")
            messagebox.showwarning("Part numbers taken", import_table.import_conflict_text(error.conflicts, error.renumbered),
                                   parent=self)
        elif isinstance(error, import_errors.ImportCancelled):
            self._rebuild()
            self._say("Import cancelled. Nothing was added to the vault, and your files were not changed.", "warn")
        else:
            self._rebuild()
            self._say("The import did not go ahead, and nothing was added to the vault.", "error")
            messagebox.showerror("Import CAD", error_text.shorten(self._error_text(error)), parent=self)

    def _cancel_job(self):
        if self.running:
            self.session.cancel()
            self.secondary.configure(state="disabled")
            self._say("Cancelling... removing anything already copied.", "warn")

    def _close(self):
        if self.running:
            if messagebox.askyesno("Import CAD", "Cancel the import in progress? Anything already copied will be "
                                                 "removed.", parent=self):
                self.closing = True
                self._cancel_job()
            return
        if self.mode == "table" and self.session.prepared and messagebox.askyesno(
                "Import CAD", "Close without importing? Nothing has been added to the vault. The scan stays saved "
                              "and can be opened again.", parent=self) is False:
            return
        self._really_close()

    def _really_close(self):
        if self.closed:
            return
        self.closed = True
        self._end_edit()
        try:
            self.session.close()
        finally:
            try:
                self.grab_release()
            except tk.TclError:
                pass
            self.destroy()
