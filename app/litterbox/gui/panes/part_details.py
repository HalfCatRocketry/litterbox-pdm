"""
part_details.py - PartDetailsView: everything about one part, in tabs. Details (pick a revision to see its state,
release, sign-offs and ECO), History (everything that happened, with buttons to open older revisions), and, in the
main window's pane, Uses, Where used and BOM (the bill of materials, single level, indented or every part once, with
Export...). The main window's right-hand pane and the pop-out Details window both use
it; show() fills it for another part without building it again.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import part_details_text
from litterbox.gui.logic import reference_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.references import bom

USES_COLUMNS = (("pn", "Part", 90), ("name", "Name", 160), ("rev", "Rev used", 70), ("latest", "Latest released", 100),
                ("state", "State", 200))


USED_IN_COLUMNS = (("pn", "Assembly", 90), ("name", "Name", 160), ("rev", "Its rev", 60), ("status", "Its status", 80),
                   ("used", "Rev of this part", 100), ("state", "State", 200))


HISTORY_COLUMNS = (("when", "When", 130), ("who", "Who", 100), ("what", "What", 90), ("details", "Details", 360))


def _table(parent, columns, height=None, stretch_last=True):
    """A dark table with sortable headings and a scroll bar, in a frame of its own. Returns (frame, tree, sorter)."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    options = {"height": height} if height else {}
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse", **options)
    for index, (name, _title, width) in enumerate(columns):
        tree.column(name, width=width, minwidth=40, anchor="w", stretch=stretch_last and index == len(columns) - 1)
    sorter = table_sorting.TableSorter(tree, [(c[0], c[1]) for c in columns])
    tree.grid(row=0, column=0, sticky="nsew")
    scroll = ctk.CTkScrollbar(frame, command=tree.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    return frame, tree, sorter


class PartDetailsView(ctk.CTkFrame):
    """on_open(rev, drawing) opens a revision's file; on_view_eco(number) shows an ECO; with references=True there
    are Uses and Where used tabs, filled by show_references(), and a BOM tab: on_bom(rev, mode) asks for it to be
    read (show_bom() fills it) and on_export_bom(rev, mode) exports it. on_tab(name) says which tab was chosen."""

    def __init__(self, master, on_open=None, on_view_eco=None, references=False, on_tab=None,
                 on_manage_references=None, on_bom=None, on_export_bom=None):
        super().__init__(master, fg_color="transparent")
        self.on_open, self.on_view_eco, self.on_tab = on_open, on_view_eco, on_tab
        self.on_manage_references = on_manage_references
        self.on_bom, self.on_export_bom = on_bom, on_export_bom
        self.record, self.revisions = None, {}
        self.eco_number, self.shown = None, []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL, command=self._tab_changed)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        names = ("Details", "History") + (("Uses", "Where used", "BOM") if references else ())
        for name in names:
            self.tabs.add(name)
            self.tabs.tab(name).columnconfigure(0, weight=1)
        self._details_tab(self.tabs.tab("Details"))
        self._history_tab(self.tabs.tab("History"))
        self.reference_trees = {}
        if references:
            for name, columns in (("Uses", USES_COLUMNS), ("Where used", USED_IN_COLUMNS)):
                self._references_tab(self.tabs.tab(name), name, columns)
        self.bom_tree = None
        if references:
            self._bom_tab(self.tabs.tab("BOM"))
        self.tabs.set("Details")

    def current_tab(self):
        return self.tabs.get()

    def _tab_changed(self):
        if self.on_tab:
            self.on_tab(self.tabs.get())

    # -- Details ---------------------------------------------------------------
    def _details_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        ctk.CTkLabel(bar, text="Revision:").grid(row=0, column=0, padx=(0, 8))
        self.rev_var = tk.StringVar(value="")
        self.rev_menu = ctk.CTkOptionMenu(bar, variable=self.rev_var, values=[""], width=90, height=28,
                                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                          button_hover_color=theme.ACCENT, command=lambda value: self._show_revision())
        self.rev_menu.grid(row=0, column=1)
        self.eco_button = release_button.ReleaseButton(bar, text="View ECO", width=90, height=28, fg_color=theme.ACCENT,
                                                       hover_color="#18527f", command=self._view_eco)
        self.eco_button.grid(row=0, column=2, padx=(10, 0))
        self.fields = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.fields.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 4))
        self.fields.columnconfigure(1, weight=1)
        self.fields.bind("<Configure>", lambda event: self._wrap(event.width), add="+")
        self.wrap_width = 260

    def _wrap(self, width=None):
        """Wrap the values to what is left of the tab beside the labels. The event says pixels; labels want sizes at
        100%, so both are divided by the display scaling."""
        if width is None:
            width = self.fields.winfo_width()
        labels = [child.winfo_reqwidth() for child in self.fields.grid_slaves(column=0)]
        scale = scaling.scale_of(self)
        wanted = max((width - max(labels or [0])) / scale - 40, 100)
        if abs(wanted - self.wrap_width) > 4:
            self.wrap_width = wanted
            for child in self.fields.grid_slaves(column=1):
                child.configure(wraplength=wanted)

    def _show_revision(self):
        """Fill the Details tab for the revision picked."""
        for child in self.fields.winfo_children():
            child.destroy()
        if self.record is None:
            return
        rev = self.rev_var.get()
        self.shown = part_details_text.revision_details(self.record, rev, self.revisions)
        for number, (label, text) in enumerate(self.shown):
            ctk.CTkLabel(self.fields, text=label + ":", text_color=theme.MUTED, anchor="nw").grid(
                row=number, column=0, sticky="nw", padx=(4, 10), pady=2)
            ctk.CTkLabel(self.fields, text=text, anchor="w", justify="left", wraplength=self.wrap_width).grid(
                row=number, column=1, sticky="w", pady=2)
        self.after_idle(self._wrap)
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
        box = ctk.CTkFrame(tab, fg_color="transparent")
        box.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        box.columnconfigure(0, weight=1)
        self.rev_tree = ttk.Treeview(box, columns=("rev", "state", "details"), show="headings", height=3,
                                     selectmode="browse")
        for name, title, width in (("rev", "Rev", 50), ("state", "State", 130), ("details", "Details", 300)):
            self.rev_tree.heading(name, text=title, anchor="w")
            self.rev_tree.column(name, width=width, minwidth=40, anchor="w", stretch=name == "details")
        self.rev_tree.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        if self.on_open:
            buttons = ctk.CTkFrame(box, fg_color="transparent")
            buttons.grid(row=0, column=1, sticky="n")
            release_button.ReleaseButton(buttons, text="Open", width=100, height=28, fg_color=theme.TEAL,
                                         hover_color=theme.TEAL_HOVER, command=lambda: self._open(False)).grid(
                row=0, column=0, pady=(0, 6))
            release_button.ReleaseButton(buttons, text="Open Drawing", width=100, height=28, fg_color=theme.TEAL,
                                         hover_color=theme.TEAL_HOVER, command=lambda: self._open(True)).grid(
                row=1, column=0)
        frame, self.tree, self.sorter = _table(tab, HISTORY_COLUMNS)
        frame.grid(row=1, column=0, sticky="nsew")

    def _open(self, drawing):
        chosen = self.rev_tree.selection()
        if chosen and self.on_open:
            self.on_open(chosen[0], drawing)

    # -- Uses / Where used -------------------------------------------------------
    def _references_tab(self, tab, name, columns):
        tab.rowconfigure(1, weight=1)
        note = ctk.CTkLabel(tab, text="", text_color=theme.MUTED, anchor="w", justify="left")
        note.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        frame, tree, _sorter = _table(tab, columns)
        frame.grid(row=1, column=0, sticky="nsew")
        if self.on_manage_references:
            release_button.ReleaseButton(tab, text="Update references...", height=28, fg_color=theme.GRAY,
                                         hover_color=theme.GRAY_HOVER, command=self.on_manage_references).grid(
                row=2, column=0, sticky="w", pady=(6, 0))
        self.reference_trees[name] = (tree, note)

    def show_references(self, uses_list=None, used_list=None, message=""):
        """Fill the Uses and Where used tabs (None: not loaded yet, and `message` says why)."""
        for name, items, table in (("Uses", uses_list, reference_text.uses_table),
                                   ("Where used", used_list, reference_text.used_in_table)):
            if name not in self.reference_trees:
                continue
            tree, note = self.reference_trees[name]
            tree.delete(*tree.get_children())
            if items is None:
                note.configure(text=message)
                continue
            for iid, values, _can_change in table(items):
                tree.insert("", "end", iid=iid, values=values[1:])
            empty = "It uses no other parts." if name == "Uses" else "No assembly uses it."
            note.configure(text=empty if not items else f"{len(items)} part{'s' if len(items) != 1 else ''}")

    # -- BOM -----------------------------------------------------------------------------
    def _bom_tab(self, tab):
        tab.rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        self.bom_rev = tk.StringVar(value="")
        self.bom_rev_menu = ctk.CTkOptionMenu(bar, variable=self.bom_rev, values=[""], width=80, height=28,
                                              fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                              button_hover_color=theme.ACCENT, command=lambda value: self._bom_changed())
        self.bom_rev_menu.grid(row=0, column=0, padx=(0, 8))
        self.bom_mode = tk.StringVar(value=bom.MODE_LABEL[bom.INDENTED])
        ctk.CTkOptionMenu(bar, variable=self.bom_mode, values=[bom.MODE_LABEL[m] for m in bom.MODES], width=140,
                          height=28, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                          button_hover_color=theme.ACCENT, command=lambda value: self._bom_changed()).grid(
            row=0, column=1, padx=(0, 8))
        release_button.ReleaseButton(bar, text="Export...", width=90, height=28, fg_color=theme.ACCENT,
                                     hover_color="#18527f", command=self._export_bom).grid(row=0, column=2)
        self.bom_note = ctk.CTkLabel(tab, text="", text_color=theme.MUTED, anchor="w", justify="left",
                                     wraplength=320)
        self.bom_note.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
        frame, self.bom_tree, _sorter = _table(tab, bom_text.COLUMNS)
        frame.grid(row=2, column=0, sticky="nsew")

    def bom_choice(self):
        """(revision, mode) picked on the BOM tab."""
        modes = {label: mode for mode, label in bom.MODE_LABEL.items()}
        return self.bom_rev.get(), modes.get(self.bom_mode.get(), bom.INDENTED)

    def _bom_changed(self):
        if self.on_bom and self.record is not None:
            self.on_bom(*self.bom_choice())

    def _export_bom(self):
        if self.on_export_bom and self.record is not None:
            self.on_export_bom(*self.bom_choice())

    def show_bom(self, rows=None, note=""):
        """Fill the BOM tab with bom_text.table rows (None: not read yet, and `note` says why)."""
        if self.bom_tree is None:
            return
        self.bom_tree.delete(*self.bom_tree.get_children())
        for iid, values in rows or []:
            self.bom_tree.insert("", "end", iid=iid, values=values)
        self.bom_note.configure(text=note)

    # -- filling it in -------------------------------------------------------------
    def show(self, record, revisions=None):
        """Show a part (a records Record); `revisions` is {revision: [files]}."""
        self.record, self.revisions = record, revisions or {}
        choices = part_details_text.revision_choices(record, self.revisions) or [record.revision]
        self.rev_menu.configure(values=choices)
        self.rev_var.set(choices[0])
        self._show_revision()
        self.rev_tree.delete(*self.rev_tree.get_children())
        revision_rows = history_text.revision_rows(record, self.revisions)
        for row in revision_rows:
            self.rev_tree.insert("", "end", iid=row[0], values=row)
        if revision_rows:
            self.rev_tree.selection_set(revision_rows[0][0])
        self.tree.delete(*self.tree.get_children())
        for row in history_text.format_history(record):
            self.tree.insert("", "end", values=row)
        self.sorter.apply()
        self.show_references(None, None, "")
        if self.bom_tree is not None:
            self.bom_rev_menu.configure(values=choices)
            self.bom_rev.set(choices[0])
            self.show_bom(None, "")
