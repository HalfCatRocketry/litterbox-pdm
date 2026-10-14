"""
pick_page.py - page 1 of the Import window: choosing folders (or a manifest), COTS, and the scan.
"""

import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.logic import error_text
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import release_button
from litterbox.importing import import_errors
from litterbox.user import settings


class PickPage:
    """page 1 of the Import window: choosing folders (or a manifest), COTS, and the scan. (part of the Import window)."""

    def _build_pick_page(self):
        page = self.pick_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ctk.CTkLabel(page, text="Folders to import (everything inside them is included)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=24, pady=(10, 4))
        self.folder_list = tk.Listbox(page, bg=theme.BG_PANEL, fg="#e6e6e6", selectbackground=theme.ACCENT, borderwidth=0,
                                      highlightthickness=0, font=("Segoe UI", 10), activestyle="none")
        self.folder_list.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 8))
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 8))
        for column, (text, command) in enumerate((("Add folder...", self._add_folder),
                                                  ("Remove selected", self._remove_folder),
                                                  ("Open a saved scan...", self._open_manifest))):
            release_button.ReleaseButton(row, text=text, command=command, height=34, fg_color=theme.GRAY,
                          hover_color=theme.GRAY_HOVER).grid(row=0, column=column, padx=(0 if column == 0 else 8, 0))
        ctk.CTkLabel(page, text="Scanning looks at file names only. Nothing is opened, changed or moved."
                                + ("" if self.cots else " Purchased (COTS) parts are brought in with Import COTS."),
                     text_color=theme.MUTED, anchor="w", justify="left", wraplength=900).grid(
            row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        self.cots_var = tk.BooleanVar(value=False)
        if self.cots:
            ctk.CTkCheckBox(page, text="I confirm that every file in these folders is a purchased part that I have "
                                       "NOT modified.", variable=self.cots_var, width=60).grid(
                row=4, column=0, sticky="w", padx=24, pady=(4, 6))

    def _add_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Folder with CAD files to import")
        if folder and folder not in self.folders:
            self.folders.append(folder)
            self.folder_list.insert("end", folder)

    def _remove_folder(self):
        for index in reversed(self.folder_list.curselection()):
            self.folder_list.delete(index)
            del self.folders[index]

    def _cots_ok(self):
        """Import COTS only starts once the user has ticked the confirmation box."""
        if self.cots and not self.cots_var.get():
            self._say("Tick the box to confirm that everything you are importing is a purchased, unmodified part.",
                      "warn")
            return False
        return True

    def _scan(self):
        if not self._cots_ok():
            return
        if not self.folders:
            self._say("Add at least one folder first.", "warn")
            return
        self._start_job(dict(folders=list(self.folders)), "Scanning...")

    def _open_manifest(self):
        path = filedialog.askopenfilename(parent=self, title="Open a saved scan",
                                          initialdir=str(settings.ROOT / "imports"),
                                          filetypes=[("Litterbox scan", "*.yaml *.yml"), ("All files", "*.*")])
        if path and self._cots_ok():
            self._start_job(dict(manifest_path=path), "Opening the saved scan...")

    def _prepared(self, proposal, error):
        if error is not None:
            self._show("pick")
            if isinstance(error, import_errors.ImportCancelled):
                self._say("Cancelled. Nothing was changed.", "warn")
            else:
                self._say("The scan could not be completed.", "error")
                messagebox.showerror("Import CAD", error_text.shorten(self._error_text(error)), parent=self)
            return
        self.conflicts, self.renumbered = [], []
        self.family_applied = None
        self.family_var.set(False)
        self.family_placeholder = number_input.import_base_placeholder(self.repo, self.session.prepared.proposal.org)
        self.family_entry.configure(placeholder_text=self.family_placeholder)
        self._show("table")
        self._rebuild()
        self._say(f"Scan saved to {self.session.manifest_path}. Review the table, then press Finish & Import.\n"
                  + self.session.prepared.proposal.note)
        if self.cots:
            self._check_duplicates()
