"""
history_window.py - a part's history, with buttons to open older revisions.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import history_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting


class HistoryWindow(ctk.CTkToplevel):
    """A pop-up table of everything that has happened to one part."""

    def __init__(self, parent, record, revisions=None, on_open=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title(f"History - {record.pn}")
        self.geometry("820x600")
        self.minsize(560, 400)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.on_open = on_open

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        ctk.CTkLabel(
            header, text=f"{record.pn}   {record.name}",
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header, text=f"Status: {record.status}     Created by {record.created_by}"
                         + ("     COTS" if record.cots else ""),
            text_color=theme.MUTED, anchor="w",
        ).grid(row=1, column=0, sticky="w")
        extra = [text for text in (record.description,
                                   f"Imported from: {record.import_path}" if record.import_path else "") if text]
        if extra:
            ctk.CTkLabel(header, text="\n".join(extra), text_color=theme.MUTED, anchor="w", justify="left",
                         wraplength=760).grid(row=2, column=0, sticky="w")

        # The revisions of this part, with buttons to open one
        revision_rows = history_text.revision_rows(record, revisions or {})
        box = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        box.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
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
        if on_open:
            buttons = ctk.CTkFrame(box, fg_color="transparent")
            buttons.grid(row=0, column=1, padx=(0, 8), pady=8)
            release_button.ReleaseButton(buttons, text="Open", width=110, fg_color=theme.TEAL, hover_color=theme.TEAL_HOVER,
                          command=lambda: self._open(False)).grid(row=0, column=0, pady=(0, 6))
            release_button.ReleaseButton(buttons, text="Open Drawing", width=110, fg_color=theme.TEAL, hover_color=theme.TEAL_HOVER,
                          command=lambda: self._open(True)).grid(row=1, column=0)

        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))
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
        self.after(100, self.lift)

    def _open(self, drawing):
        chosen = self.rev_tree.selection()
        if chosen and self.on_open:
            self.on_open(chosen[0], drawing)
