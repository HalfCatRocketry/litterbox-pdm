"""
generate_files_dialog.py - Generate STEP/PDF: which files to make (STEP, PDF or both), where (in Litterbox, with the
working revision, or a folder outside it), an Admin's "make them again", and a table of the parts with what will
happen to each (gui/logic/generate_text.py).
"""

import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk

from litterbox.exporting import export_folder
from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import generate_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.records import record_exports

KIND_TEXT = {record_exports.STEP: "STEP (AP214)", record_exports.PDF: "PDF of the drawing (every sheet)"}


class GenerateFilesDialog(modal_dialog.ModalDialog):
    """GenerateFilesDialog(parent, title, rows, folder, litterbox_root, may_vault, is_admin).show()
    -> None if cancelled, else {"kinds": [...], "where": IN_VAULT or OUTSIDE, "folder": Path or None,
    "force": bool, "pns": [the parts that will be done]}. `rows` are the parts' PartStatus rows. Without
    `may_vault` (read-only access) only a folder outside Litterbox can be chosen."""

    def __init__(self, parent, title, rows, folder, litterbox_root, may_vault=True, is_admin=False):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.rows, self.litterbox_root = None, list(rows), litterbox_root
        self.table_rows = []
        width, height = 640, 600
        self.title("Generate STEP/PDF")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.minsize(520, 480)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(7, weight=1)

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text="Files to make, from the working revision", anchor="w").grid(
            row=1, column=0, sticky="ew", padx=20)
        kinds = ctk.CTkFrame(self, fg_color="transparent")
        kinds.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 8))
        self.kinds = {}
        for number, kind in enumerate(record_exports.KINDS):
            flag = tk.BooleanVar(master=self, value=True)
            ctk.CTkCheckBox(kinds, text=KIND_TEXT[kind], variable=flag, command=self._fill).grid(
                row=0, column=number, sticky="w", padx=(0, 20), pady=2)
            self.kinds[kind] = flag

        self.where = tk.StringVar(master=self, value=generate_text.IN_VAULT if may_vault else generate_text.OUTSIDE)
        where = ctk.CTkFrame(self, fg_color="transparent")
        where.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 4))
        for number, key in enumerate((generate_text.IN_VAULT, generate_text.OUTSIDE)):
            ctk.CTkRadioButton(where, text=generate_text.WHERE_LABEL[key], variable=self.where, value=key,
                               command=self._fill, state="normal" if may_vault or key == generate_text.OUTSIDE
                               else "disabled").grid(row=number, column=0, sticky="w", pady=2)

        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.grid(row=4, column=0, sticky="ew", padx=(48, 20), pady=(0, 4))
        folder_row.columnconfigure(0, weight=1)
        self.folder_entry = ctk.CTkEntry(folder_row, height=32)
        self.folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.folder_entry.insert(0, str(folder))
        self.browse = release_button.ReleaseButton(folder_row, text="Browse...", width=90, height=32,
                                                   fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                                   command=self._browse)
        self.browse.grid(row=0, column=1)

        self.force = tk.BooleanVar(master=self, value=False)
        self.force_box = ctk.CTkCheckBox(self, text="Make released parts' files again, even if up to date (Admin)",
                                         variable=self.force, command=self._fill)
        if is_admin:
            self.force_box.grid(row=5, column=0, sticky="w", padx=20, pady=(4, 4))

        ctk.CTkLabel(self, text="Parts", anchor="w").grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 0))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=7, column=0, sticky="nsew", padx=20, pady=(2, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        scale = scaling.scale_of(self)
        self.tree = ttk.Treeview(frame, columns=("pn", "rev", "what"), show="headings", selectmode="none")
        for name, heading, size in (("pn", "Part", 140), ("rev", "Rev", 50), ("what", "What happens", 360)):
            self.tree.heading(name, text=heading, anchor="w")
            self.tree.column(name, width=int(size * scale), anchor="w", stretch=name == "what")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w")
        self.note.grid(row=8, column=0, sticky="ew", padx=20, pady=(4, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=580)
        self.problem.grid(row=9, column=0, sticky="ew", padx=20, pady=(2, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=10, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Generate", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._generate).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _chosen_kinds(self):
        return [kind for kind, flag in self.kinds.items() if flag.get()]

    def _fill(self):
        """Show what will happen to each part with the choices as they are now."""
        outside = self.where.get() == generate_text.OUTSIDE
        state = "normal" if outside else "disabled"
        self.folder_entry.configure(state=state)
        self.browse.configure(state=state)
        self.force_box.configure(state="disabled" if outside else "normal")
        self.table_rows = generate_text.table(self.rows, self._chosen_kinds(), self.where.get(),
                                              bool(self.force.get()) and not outside)
        self.tree.delete(*self.tree.get_children())
        for row in self.table_rows:
            self.tree.insert("", "end", iid=str(row.pn), values=(str(row.pn), row.revision, row.what))
        self.note.configure(text=generate_text.count_text(self.table_rows))

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self, title="Save the files in which folder?",
                                         initialdir=self.folder_entry.get() or None)
        if chosen:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)

    def _generate(self):
        kinds = self._chosen_kinds()
        if not kinds:
            self.problem.configure(text="Choose STEP, PDF or both.")
            return
        pns = [row.pn for row in self.table_rows if row.runs]
        if not pns:
            self.problem.configure(text="None of these parts can have the files chosen made here.")
            return
        folder = None
        if self.where.get() == generate_text.OUTSIDE:
            try:
                folder = export_folder.check(self.folder_entry.get(), self.litterbox_root)
            except export_folder.ExportError as e:
                self.problem.configure(text=str(e))
                return
        self.result = {"kinds": kinds, "where": self.where.get(), "folder": folder,
                       "force": bool(self.force.get()) and folder is None, "pns": pns}
        self.destroy()
