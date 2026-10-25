"""
document_window.py - one document's details in a window of its own (Details... on the Documents screen), in four
tabs: Details (pick a revision to see its state, release, sign-offs and ECO), Files (that revision's files, to open),
History (everything that happened) and Where linked (the part revisions that link to it). A part's pop-out is
windows/history_window.py; a document has no Uses, Where used or BOM.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import document_details_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import part_details_text
from litterbox.gui.panes import part_details
from litterbox.gui.widgets import release_button


class DocumentWindow(ctk.CTkToplevel):
    """A pop-up about one document. `revisions` is {revision: [files]}; `types_by_key` names its type.
    on_open_file(path) opens one of its files, on_view_eco(number) shows an ECO, on_show_part(pn) shows a linking
    part's own Details. The Where linked tab is filled by show_links(), once the main window has read it."""

    def __init__(self, parent, record, revisions=None, types_by_key=None, on_open_file=None, on_view_eco=None,
                 on_show_part=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.record, self.revisions, self.types_by_key = record, revisions or {}, types_by_key or {}
        self.on_open_file, self.on_view_eco, self.on_show_part = on_open_file, on_view_eco, on_show_part
        self.scale = scaling.scale_of(self)
        self.eco_number, self.links = None, {}
        self.title(f"{record.pn} - Details")
        window_chrome.set_size(self, 820, 600)
        window_chrome.min_size(self, 560, 420)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"{record.pn}   {record.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        for name in ("Details", "Files", "History", "Where linked"):
            self.tabs.add(name)
            self.tabs.tab(name).columnconfigure(0, weight=1)
        self._details_tab(self.tabs.tab("Details"))
        self._files_tab(self.tabs.tab("Files"))
        self._history_tab(self.tabs.tab("History"))
        self._linked_tab(self.tabs.tab("Where linked"))
        self.tabs.set("Details")
        self._show_revision()
        self.after(100, self.lift)

    def _revision_menu(self, bar, variable):
        choices = part_details_text.revision_choices(self.record, self.revisions) or [self.record.revision]
        variable.set(choices[0])
        menu = ctk.CTkOptionMenu(bar, variable=variable, values=choices, width=90, height=28, fg_color=theme.GRAY,
                                 button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                                 command=lambda value: self._show_revision())
        menu.grid(row=0, column=1)
        return menu

    # -- Details ---------------------------------------------------------------
    def _details_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        ctk.CTkLabel(bar, text="Revision:").grid(row=0, column=0, padx=(0, 8))
        self.rev_var = tk.StringVar(value="")
        self._revision_menu(bar, self.rev_var)
        self.eco_button = release_button.ReleaseButton(bar, text="View ECO", width=90, height=28, fg_color=theme.ACCENT,
                                                       hover_color="#18527f", command=self._view_eco)
        self.eco_button.grid(row=0, column=2, padx=(10, 0))
        self.fields = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.fields.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        self.fields.columnconfigure(1, weight=1)

    def _show_revision(self):
        """Fill the Details and Files tabs for the revision picked."""
        rev = self.rev_var.get()
        for child in self.fields.winfo_children():
            child.destroy()
        shown = document_details_text.revision_details(self.record, rev, self.revisions, self.types_by_key)
        for number, (label, text) in enumerate(shown):
            ctk.CTkLabel(self.fields, text=label + ":", text_color=theme.MUTED, anchor="nw").grid(
                row=number, column=0, sticky="nw", padx=(4, 10), pady=2)
            ctk.CTkLabel(self.fields, text=text, anchor="nw", justify="left", wraplength=520).grid(
                row=number, column=1, sticky="nw", pady=2)       # top-aligned with its label, even wrapped
        self.eco_number, _how = part_details_text.eco_for(self.record, rev)
        if self.eco_number and self.on_view_eco:
            self.eco_button.grid()
        else:
            self.eco_button.grid_remove()
        self.files_tree.delete(*self.files_tree.get_children())
        rows = document_details_text.file_rows(self.revisions, rev)
        for path, values in rows:
            self.files_tree.insert("", "end", iid=path, values=values)
        if rows:
            self.files_tree.selection_set(rows[0][0])
        self.files_label.configure(text=f"Rev {rev}: " + (f"{len(rows)} file{'s' if len(rows) != 1 else ''}"
                                                          if rows else "no files"))

    def _view_eco(self):
        if self.eco_number and self.on_view_eco:
            self.on_view_eco(self.eco_number)

    # -- Files -----------------------------------------------------------------
    def _files_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        release_button.ReleaseButton(bar, text="Open", width=90, height=28, fg_color=theme.TEAL,
                                     hover_color=theme.TEAL_HOVER, command=self._open_file).grid(row=0, column=0)
        self.files_label = ctk.CTkLabel(bar, text="", text_color=theme.MUTED, anchor="w")
        self.files_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        frame, self.files_tree, _sorter = part_details.make_table(tab, document_details_text.FILE_COLUMNS,
                                                                  scale=self.scale)
        frame.grid(row=1, column=0, sticky="nsew")
        self.files_tree.bind("<Double-1>", lambda event: self._open_file())

    def _open_file(self):
        chosen = self.files_tree.selection()
        if chosen and self.on_open_file:
            self.on_open_file(chosen[0])

    # -- History ---------------------------------------------------------------
    def _history_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        revisions = ttk.Treeview(tab, columns=("rev", "state", "details"), show="headings", height=3,
                                 selectmode="none")
        for name, title, width in part_details.REVISION_COLUMNS:
            revisions.heading(name, text=title, anchor="w")
            revisions.column(name, width=round(width * self.scale), minwidth=round(40 * self.scale), anchor="w",
                             stretch=name == "details")
        revisions.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        for row in history_text.revision_rows(self.record, self.revisions):
            revisions.insert("", "end", iid=row[0], values=row)
        frame, tree, sorter = part_details.make_table(tab, part_details.HISTORY_COLUMNS, scale=self.scale)
        frame.grid(row=1, column=0, sticky="nsew")
        for row in history_text.format_history(self.record):
            tree.insert("", "end", values=row)
        sorter.apply()

    # -- Where linked ----------------------------------------------------------
    def _linked_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        release_button.ReleaseButton(bar, text="Part Details", width=100, height=28, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self._show_part).grid(row=0, column=0)
        self.linked_label = ctk.CTkLabel(bar, text="Reading...", text_color=theme.MUTED, anchor="w")
        self.linked_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        frame, self.linked_tree, _sorter = part_details.make_table(tab, document_details_text.LINKED_COLUMNS,
                                                                   scale=self.scale)
        frame.grid(row=1, column=0, sticky="nsew")
        self.linked_tree.bind("<Double-1>", lambda event: self._show_part())

    def show_links(self, links, rows_by_pn, message=""):
        """Fill the Where linked tab: `links` is [(PN, revision)], or None with `message` saying why not."""
        self.linked_tree.delete(*self.linked_tree.get_children())
        self.links = {}
        if links is None:
            self.linked_label.configure(text=message)
            return
        for iid, values in document_details_text.linked_rows(links, rows_by_pn):
            self.linked_tree.insert("", "end", iid=iid, values=values)
        self.links = {f"{pn}|{rev}": pn for pn, rev in links}
        self.linked_label.configure(text=document_details_text.linked_note(links))

    def _show_part(self):
        chosen = self.linked_tree.selection()
        if chosen and chosen[0] in self.links and self.on_show_part:
            self.on_show_part(self.links[chosen[0]])
        elif self.links:
            self.linked_label.configure(text="Click a part first.")
