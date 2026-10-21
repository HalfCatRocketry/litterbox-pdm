"""
documents_screen.py - the Documents screen: every document in the vault (PROP-0001 and so on), searchable and
filtered by type, with New Document and the actions a document goes through: its files (Open, Add Files..., Remove
File...), check out and in, release, revise, unrelease and void. A screen of the main window, chosen in the sidebar.

The actions are the main window's own (App.act_on points them at the documents chosen here), so a document gets
the same checks, questions and workflows as a part; documents have workflow templates of their own.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.documents import doc_types
from litterbox.errors import LitterboxError
from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import document_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting


class DocumentsScreen(ctk.CTkFrame):
    """The list of documents. reload() fills it from the main window's document rows (app.doc_rows)."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app, self.types = app, []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        ctk.CTkLabel(self, text="Documents", font=ctk.CTkFont(size=18, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=16)
        bar.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        ctk.CTkEntry(bar, textvariable=self.search_var, height=34,
                     placeholder_text="Search by number, title, description, type or status").grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_var.trace_add("write", lambda *_: self._fill())
        self.type_var = tk.StringVar(value=document_text.ALL_TYPES)
        self.type_menu = ctk.CTkOptionMenu(bar, variable=self.type_var, values=[document_text.ALL_TYPES], width=190,
                                           height=34, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                           button_hover_color=theme.ACCENT, command=lambda value: self._fill())
        self.type_menu.grid(row=0, column=1)

        rows = (
            (("New Document...", app.new_document, theme.GREEN, theme.GREEN_HOVER),
             ("Open", lambda: self._one(app.open_document), theme.TEAL, theme.TEAL_HOVER),
             ("Add Files...", lambda: self._one(app.add_document_files), None, None),
             ("Remove File...", lambda: self._one(app.remove_document_file), None, None),
             ("Details...", lambda: self._act(app.show_history), None, None)),
            (("Check Out", lambda: self._act(app.check_out), None, None),
             ("Check In", lambda: self._act(app.check_in), None, None),
             ("Undo Checkout", lambda: self._act(app.undo_checkout), None, None),
             ("Release", lambda: self._act(app.release), None, None),
             ("Revise", lambda: self._act(app.revise), None, None),
             ("Cancel Revision", lambda: self._act(app.cancel_revision), None, None),
             ("Unrelease", lambda: self._act(app.reopen), None, None),
             ("Void", lambda: self._act(app.void), None, None)),
        )
        for number, buttons in enumerate(rows, start=2):
            line = ctk.CTkFrame(self, fg_color="transparent")
            line.grid(row=number, column=0, sticky="w", padx=16, pady=(8 if number == 2 else 4, 0))
            for column, (text, command, color, hover) in enumerate(buttons):
                release_button.ReleaseButton(line, text=text, width=110, height=30, fg_color=color or theme.GRAY,
                                             hover_color=hover or theme.GRAY_HOVER, command=command).grid(
                    row=0, column=column, padx=(0, 6))

        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        scale = scaling.scale_of(self)
        self.tree = ttk.Treeview(frame, columns=[name for name, _t, _w in document_text.COLUMNS], show="headings",
                                 selectmode="extended")
        for name, _title, width in document_text.COLUMNS:
            self.tree.column(name, width=int(width * scale), anchor="w")
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w in document_text.COLUMNS])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", lambda event: self._one(app.open_document))
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=860)
        self.note.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 16))

    def reload(self):
        """Fill the list again from the main window's latest document rows, keeping the search and selection."""
        try:
            self.types = doc_types.load(self.app.repo())
        except LitterboxError as e:
            self.types = []
            self.note.configure(text=str(e))
        self.type_menu.configure(values=document_text.type_filters(self.types, self.app.doc_rows))
        self._fill()

    def _fill(self):
        chosen = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        rows = document_text.table(list(self.app.doc_rows), doc_types.by_key(self.types), self.search_var.get(),
                                   self.type_var.get())
        for iid, values in rows:
            self.tree.insert("", "end", iid=iid, values=values)
        self.sorter.apply()
        keep = [iid for iid in chosen if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(*keep)
        if not self.types:
            self.note.configure(text="This org has no document types yet. An Admin adds them in Team > Document "
                                     "Types..., then New Document can number documents of each type.")
        else:
            total = len(self.app.doc_rows)
            self.note.configure(text=f"{len(rows)} of {total} document{'s' if total != 1 else ''} shown"
                                if len(rows) != total else f"{total} document{'s' if total != 1 else ''}")

    def _chosen(self):
        rows = {str(row.pn): row.pn for row in self.app.doc_rows}
        return [rows[iid] for iid in self.tree.selection() if iid in rows]

    def _act(self, method):
        numbers = self._chosen()
        if not numbers:
            self.note.configure(text="Click a document first (Ctrl or Shift picks several).")
            return
        self.app.act_on(numbers, method)

    def _one(self, method):
        numbers = self._chosen()
        if len(numbers) != 1:
            self.note.configure(text="Click one document first.")
            return
        method(numbers[0])
