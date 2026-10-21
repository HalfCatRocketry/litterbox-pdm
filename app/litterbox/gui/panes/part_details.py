"""
part_details.py - PartDetailsView: everything about one part, in tabs. Details (pick a revision to see its state,
release, sign-offs and ECO), History (everything that happened, with buttons to open older revisions), Uses, Where
used and BOM (the bill of materials, single level, indented or every part once, with Export...). The main window's
right-hand pane and the pop-out Details window both use it; show() fills it for another part without building it
again.
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
from litterbox.gui.widgets import tooltip
from litterbox.references import bom

USES_COLUMNS = (("pn", "Part", 90), ("name", "Name", 160), ("rev", "Rev used", 70), ("latest", "Latest released", 100),
                ("state", "State", 200))


USED_IN_COLUMNS = (("pn", "Assembly", 90), ("name", "Name", 160), ("rev", "Rev", 60), ("status", "Status", 80),
                   ("used", "Rev used", 80), ("state", "State", 200))


HISTORY_COLUMNS = (("when", "When", 130), ("who", "Who", 100), ("what", "What", 90), ("details", "Details", 360))


REVISION_COLUMNS = (("rev", "Rev", 60), ("state", "State", 150), ("details", "Details", 300))


def _table(parent, columns, height=None, stretch_last=True, scale=1.0):
    """A dark table with sortable headings and a scroll bar, in a frame of its own. Returns (frame, tree, sorter).
    The widths are at 100%; `scale` is the display's (Tk draws the headings bigger on a scaled display)."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    options = {"height": height} if height else {}
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse", **options)
    for index, (name, _title, width) in enumerate(columns):
        tree.column(name, width=round(width * scale), minwidth=round(40 * scale), anchor="w",
                    stretch=stretch_last and index == len(columns) - 1)
    sorter = table_sorting.TableSorter(tree, [(c[0], c[1]) for c in columns])
    tree.grid(row=0, column=0, sticky="nsew")
    scroll = ctk.CTkScrollbar(frame, command=tree.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    return frame, tree, sorter


class PartDetailsView(ctk.CTkFrame):
    """on_open(rev, drawing) opens a revision's file; on_view_eco(number) shows an ECO. The Uses and Where used tabs
    are filled by show_references(), and the BOM tab by show_bom(): on_bom(rev, mode) asks for it to be read,
    on_export_bom(rev, mode) exports it and on_update_bom() counts its parts again (the Update BOM button, shown only
    when its quantities need it). on_tab(name) says which tab was chosen. on_generate(pn) makes a released part's
    STEP and PDF (the Generate STEP/PDF... button, shown only while they need updating)."""

    def __init__(self, master, on_open=None, on_view_eco=None, on_tab=None,
                 on_manage_references=None, on_bom=None, on_export_bom=None, on_update_bom=None, on_generate=None):
        super().__init__(master, fg_color="transparent")
        self.scale = scaling.scale_of(self)
        self.on_open, self.on_view_eco, self.on_tab = on_open, on_view_eco, on_tab
        self.on_manage_references = on_manage_references
        self.on_bom, self.on_export_bom, self.on_update_bom = on_bom, on_export_bom, on_update_bom
        self.on_generate = on_generate
        self.record, self.revisions = None, {}
        self.eco_number, self.shown = None, []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL, command=self._tab_changed)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        for name in ("Details", "History", "Uses", "Where used", "BOM"):
            self.tabs.add(name)
            self.tabs.tab(name).columnconfigure(0, weight=1)
        self._details_tab(self.tabs.tab("Details"))
        self._history_tab(self.tabs.tab("History"))
        self.reference_trees = {}
        for name, columns in (("Uses", USES_COLUMNS), ("Where used", USED_IN_COLUMNS)):
            self._references_tab(self.tabs.tab(name), name, columns)
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
        self.generate_button = release_button.ReleaseButton(bar, text="Generate STEP/PDF...", width=140, height=28,
                                                            fg_color=theme.ACCENT, hover_color="#18527f",
                                                            command=self._generate)
        self.generate_button.grid(row=0, column=3, padx=(10, 0))
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
        if self.on_generate and part_details_text.files_flagged(self.record, rev, self.revisions):
            self.generate_button.grid()
        else:
            self.generate_button.grid_remove()

    def _generate(self):
        if self.record is not None and self.on_generate:
            self.on_generate(self.record.pn)

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
        for name, title, width in REVISION_COLUMNS:
            self.rev_tree.heading(name, text=title, anchor="w")
            self.rev_tree.column(name, width=round(width * self.scale), minwidth=round(40 * self.scale), anchor="w",
                                 stretch=name == "details")
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
        frame, self.tree, self.sorter = _table(tab, HISTORY_COLUMNS, scale=self.scale)
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
        frame, tree, _sorter = _table(tab, columns, scale=self.scale)
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
        """The revision and kind of list on one line, Export... and Update BOM under them, so a narrow pane fits."""
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
        buttons = ctk.CTkFrame(bar, fg_color="transparent")
        buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        release_button.ReleaseButton(buttons, text="Export...", width=90, height=28, fg_color=theme.ACCENT,
                                     hover_color="#18527f", command=self._export_bom).grid(row=0, column=0)
        self.bom_update = release_button.ReleaseButton(buttons, text="Update BOM", width=100, height=28,
                                                       fg_color=theme.TEAL, hover_color=theme.TEAL_HOVER,
                                                       command=self._update_bom)
        self.bom_update.grid(row=0, column=1, padx=(8, 0))
        self.bom_update.grid_remove()
        tooltip.Tooltip(self.bom_update, bom_text.update_button_text(True))
        self.bom_note = ctk.CTkLabel(tab, text="", text_color=theme.MUTED, anchor="w", justify="left",
                                     wraplength=320)
        self.bom_note.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
        tab.bind("<Configure>", lambda event: self._wrap_bom_note(event.width), add="+")
        frame, self.bom_tree, _sorter = _table(tab, bom_text.COLUMNS, scale=self.scale)
        frame.grid(row=2, column=0, sticky="nsew")

    def _wrap_bom_note(self, width):
        """The note under the BOM tab's buttons wraps to the tab's width (the event says pixels; labels want sizes
        at 100%)."""
        self.bom_note.configure(wraplength=max(width / self.scale - 20, 120))

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

    def _update_bom(self):
        if self.on_update_bom and self.record is not None:
            self.on_update_bom()

    def show_bom(self, rows=None, note="", can_update=False):
        """Fill the BOM tab with bom_text.table rows (None: not read yet, and `note` says why). `can_update` shows
        the Update BOM button."""
        if can_update and self.on_update_bom:
            self.bom_update.grid()
        else:
            self.bom_update.grid_remove()
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
        self.bom_rev_menu.configure(values=choices)
        self.bom_rev.set(choices[0])
        self.show_bom(None, "")
