"""
export_files_dialog.py - Export Files: which kinds of file, which revision, whether an assembly brings the parts
it uses, and the folder to copy them to (outside Litterbox and every repository, see exporting/export_folder.py).
"""

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from litterbox.exporting import export_folder
from litterbox.exporting import part_files_export
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button

class ExportFilesDialog(modal_dialog.ModalDialog):
    """ExportFilesDialog(parent, title, folder, litterbox_root, has_assembly, choices, first).show()
    -> None if cancelled, else {"kinds": [...], "which": RELEASED, WORKING or a revision letter, "with_used": bool,
    "folder": Path}. `choices` are the Revision list's [(label, which)] (export_text.revision_choices), `first` the
    label chosen to start with."""

    def __init__(self, parent, title, folder, litterbox_root, has_assembly=False, choices=None, first=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.litterbox_root = None, litterbox_root
        self.choices = list(choices or [("Latest released", part_files_export.RELEASED),
                                        ("Working", part_files_export.WORKING)])
        width, height = 520, 500
        self.title("Export Files")
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text="Files to copy", anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        kinds = ctk.CTkFrame(self, fg_color="transparent")
        kinds.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 8))
        self.kinds = {}
        for number, kind in enumerate(part_files_export.KINDS):
            flag = tk.BooleanVar(master=self, value=True)
            ctk.CTkCheckBox(kinds, text=part_files_export.KIND_LABEL[kind], variable=flag).grid(
                row=number // 2, column=number % 2, sticky="w", padx=(0, 20), pady=2)
            self.kinds[kind] = flag

        ctk.CTkLabel(self, text="Revision", anchor="w").grid(row=3, column=0, sticky="ew", padx=20)
        self.which = tk.StringVar(master=self, value=first or self.choices[0][0])
        ctk.CTkOptionMenu(self, variable=self.which, values=[label for label, _which in self.choices], width=260,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
            row=4, column=0, sticky="w", padx=20, pady=(2, 2))
        ctk.CTkLabel(self, text="A part never released gives its working revision.", text_color=theme.MUTED,
                     anchor="w").grid(row=5, column=0, sticky="ew", padx=20)

        self.with_used = tk.BooleanVar(master=self, value=has_assembly)
        ctk.CTkCheckBox(self, text="Also the parts each assembly uses (the revisions it uses)",
                        variable=self.with_used, state="normal" if has_assembly else "disabled").grid(
            row=6, column=0, sticky="w", padx=20, pady=(10, 8))

        ctk.CTkLabel(self, text="Copy to (a folder outside Litterbox's folder and any repository)", anchor="w").grid(
            row=7, column=0, sticky="ew", padx=20)
        where = ctk.CTkFrame(self, fg_color="transparent")
        where.grid(row=8, column=0, sticky="ew", padx=20, pady=(2, 0))
        where.columnconfigure(0, weight=1)
        self.folder_entry = ctk.CTkEntry(where, height=32)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.folder_entry.insert(0, str(folder))
        release_button.ReleaseButton(where, text="Browse...", width=90, height=32, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self._browse).grid(row=0, column=1)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=470)
        self.problem.grid(row=9, column=0, sticky="ew", padx=20, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=10, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Export", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._export).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Export to which folder?",
                                         initialdir=self.folder_entry.get() or None)
        if chosen:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)

    def _export(self):
        kinds = [kind for kind, flag in self.kinds.items() if flag.get()]
        if not kinds:
            self.problem.configure(text="Choose at least one kind of file.")
            return
        try:
            folder = export_folder.check(self.folder_entry.get(), self.litterbox_root)
        except export_folder.ExportError as e:
            self.problem.configure(text=str(e))
            return
        which = dict(self.choices).get(self.which.get(), part_files_export.RELEASED)
        self.result = {"kinds": kinds, "which": which, "with_used": bool(self.with_used.get()), "folder": folder}
        self.destroy()
