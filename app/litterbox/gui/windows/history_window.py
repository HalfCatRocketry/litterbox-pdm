"""
history_window.py - one part's window: a Details tab (pick a revision to see its state, release, sign-offs and
ECO) and a History tab (everything that happened, with buttons to open older revisions).
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import history_text
from litterbox.gui.logic import part_details_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting


class HistoryWindow(ctk.CTkToplevel):
    """A pop-up about one part. `revisions` is {revision: [files]}; on_open(rev, drawing) opens a revision's file;
    on_view_eco(number) shows an ECO."""

    def __init__(self, parent, record, revisions=None, on_open=None, on_view_eco=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title(f"{record.pn} - Details and History")
        self.geometry("860x640")
        self.minsize(580, 440)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.record, self.revisions = record, revisions or {}
        self.on_open, self.on_view_eco = on_open, on_view_eco

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        ctk.CTkLabel(header, text=f"{record.pn}   {record.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL)
        tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        for name in ("Details", "History"):
            tabs.add(name)
            tabs.tab(name).columnconfigure(0, weight=1)
        self.tabs = tabs
        self._details_tab(tabs.tab("Details"))
        self._history_tab(tabs.tab("History"))
        tabs.set("Details")
        self.after(100, self.lift)

    # -- Details ---------------------------------------------------------------
    def _details_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        choices = part_details_text.revision_choices(self.record, self.revisions) or [self.record.revision]
        ctk.CTkLabel(bar, text="Revision:").grid(row=0, column=0, padx=(0, 8))
        self.rev_var = tk.StringVar(value=choices[0])
        ctk.CTkOptionMenu(bar, variable=self.rev_var, values=choices, width=110, height=30, fg_color=theme.GRAY,
                          button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._show_revision()).grid(row=0, column=1)
        self.eco_button = release_button.ReleaseButton(bar, text="View ECO", width=100, height=30, fg_color=theme.ACCENT,
                                                       hover_color="#18527f", command=self._view_eco)
        self.eco_button.grid(row=0, column=2, padx=(10, 0))
        self.fields = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.fields.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 8))
        self.fields.columnconfigure(1, weight=1)
        self._show_revision()

    def _show_revision(self):
        """Fill the Details tab for the revision picked."""
        for child in self.fields.winfo_children():
            child.destroy()
        rev = self.rev_var.get()
        self.shown = part_details_text.revision_details(self.record, rev, self.revisions)
        for number, (label, text) in enumerate(self.shown):
            ctk.CTkLabel(self.fields, text=label + ":", text_color=theme.MUTED, anchor="nw").grid(
                row=number, column=0, sticky="nw", padx=(4, 12), pady=2)
            ctk.CTkLabel(self.fields, text=text, anchor="w", justify="left", wraplength=620).grid(
                row=number, column=1, sticky="w", pady=2)
        self.eco_number, _how = part_details_text.eco_for(self.record, rev)
        if self.eco_number and self.on_view_eco:
            self.eco_button.grid()
        else:
            self.eco_button.grid_remove()

    def _view_eco(self):
        if self.eco_number and self.on_view_eco:
            self.on_view_eco(self.eco_number)

    # -- History ---------------------------------------------------------------
    def _history_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        record = self.record
        revision_rows = history_text.revision_rows(record, self.revisions)
        box = ctk.CTkFrame(tab, fg_color="transparent")
        box.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        box.columnconfigure(0, weight=1)
        self.rev_tree = ttk.Treeview(box, columns=("rev", "state", "details"), show="headings",
                                     height=min(max(len(revision_rows), 1), 5), selectmode="browse")
        for name, title, width in (("rev", "Rev", 60), ("state", "State", 160), ("details", "Details", 520)):
            self.rev_tree.heading(name, text=title, anchor="w")
            self.rev_tree.column(name, width=width, anchor="w")
        for row in revision_rows:
            self.rev_tree.insert("", "end", iid=row[0], values=row)
        if revision_rows:
            self.rev_tree.selection_set(revision_rows[0][0])
        self.rev_tree.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        if self.on_open:
            buttons = ctk.CTkFrame(box, fg_color="transparent")
            buttons.grid(row=0, column=1, padx=(0, 8), pady=8)
            release_button.ReleaseButton(buttons, text="Open", width=110, fg_color=theme.TEAL, hover_color=theme.TEAL_HOVER,
                          command=lambda: self._open(False)).grid(row=0, column=0, pady=(0, 6))
            release_button.ReleaseButton(buttons, text="Open Drawing", width=110, fg_color=theme.TEAL, hover_color=theme.TEAL_HOVER,
                          command=lambda: self._open(True)).grid(row=1, column=0)

        frame = ctk.CTkFrame(tab, fg_color="transparent")
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("when", "who", "what", "details"), show="headings")
        history_columns = (("when", "When", 130), ("who", "Who", 110),
                           ("what", "What", 100), ("details", "Details", 420))
        for name, _title, width in history_columns:
            self.tree.column(name, width=width, anchor="w")
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w in history_columns])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        for row in history_text.format_history(record):
            self.tree.insert("", "end", values=row)

    def _open(self, drawing):
        chosen = self.rev_tree.selection()
        if chosen and self.on_open:
            self.on_open(chosen[0], drawing)
