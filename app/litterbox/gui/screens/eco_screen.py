"""
eco_screen.py - the ECOs screen: every engineering change order in the vault, searchable, with a button to view
one. Read-only. A screen of the main window, chosen in the sidebar.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.logic import eco_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting


class EcoScreen(ctk.CTkFrame):
    """The list of ECOs. show(ecos, problems) fills it: `ecos` are change_orders Eco objects (newest first);
    `problems` is {number: why} for files that couldn't be read. on_view(eco) opens one."""

    def __init__(self, master, on_view):
        super().__init__(master, fg_color="transparent")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.ecos, self.order, self.problems, self.on_view = {}, [], {}, on_view

        ctk.CTkLabel(self, text="Engineering change orders", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=16)
        bar.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        self.entry = ctk.CTkEntry(bar, textvariable=self.search_var, height=34,
                                  placeholder_text="Search by ECO number, title, description, part or person")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_var.trace_add("write", lambda *_: self._fill())
        self.status_var = tk.StringVar(value="All")
        ctk.CTkOptionMenu(bar, variable=self.status_var, values=list(eco_text.STATUS_FILTERS), width=130, height=34,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._fill()).grid(row=0, column=1, padx=(0, 8))
        release_button.ReleaseButton(bar, text="View", width=90, height=34, fg_color=theme.ACCENT,
                                     hover_color="#18527f", command=self._view).grid(row=0, column=2)

        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[name for name, _t, _w in eco_text.TABLE_COLUMNS], show="headings",
                                 selectmode="browse")
        for name, _title, width in eco_text.TABLE_COLUMNS:
            self.tree.column(name, width=width, anchor="w")
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w in eco_text.TABLE_COLUMNS])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", lambda event: self._view())
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=860)
        self.note.grid(row=3, column=0, sticky="ew", padx=16, pady=(4, 16))

    def show(self, ecos, problems):
        """Fill the list (again), keeping the search."""
        self.ecos = {eco.number: eco for eco in ecos}
        self.order = [eco.number for eco in ecos]
        self.problems = problems
        self._fill()

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        rows = eco_text.eco_table([self.ecos[n] for n in self.order], self.search_var.get(), self.status_var.get())
        for iid, values in rows:
            self.tree.insert("", "end", iid=iid, values=values)
        self.sorter.apply()
        if not self.ecos and not self.problems:
            self.note.configure(text="There are no ECOs yet. One is made when a workflow that requires an ECO starts.")
        else:
            self.note.configure(text=eco_text.table_note(len(rows), len(self.ecos), self.problems))

    def _view(self):
        chosen = self.tree.selection()
        if not chosen:
            self.note.configure(text="Click an ECO first.")
            return
        self.on_view(self.ecos[chosen[0]])
