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
from litterbox.gui.logic import document_text
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


def make_table(parent, columns, height=None, stretch_last=True, scale=1.0):
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
    STEP and PDF (the Generate STEP/PDF... button, shown only while they need updating), and on_save_bom(pn) its BOM
    file (the Save BOM File button, shown only while the release's BOM still needs saving). on_add_bom_item() and
    on_remove_bom_item(stem) add and take off BOM lines by hand (the buttons show while you may). The Documents tab
    lists the documents linked to the revision picked on the Details tab (document_rows(record, rev) gives its
    rows); on_open_document(number), on_link_document(rev) and on_unlink_document(rev, number) are its buttons."""

    def __init__(self, master, on_open=None, on_view_eco=None, on_tab=None,
                 on_manage_references=None, on_bom=None, on_export_bom=None, on_update_bom=None, on_generate=None,
                 on_add_bom_item=None, on_remove_bom_item=None, document_rows=None, on_open_document=None,
                 on_link_document=None, on_unlink_document=None, on_save_bom=None):
        super().__init__(master, fg_color="transparent")
        self.scale = scaling.scale_of(self)
        self.on_open, self.on_view_eco, self.on_tab = on_open, on_view_eco, on_tab
        self.on_manage_references = on_manage_references
        self.on_bom, self.on_export_bom, self.on_update_bom = on_bom, on_export_bom, on_update_bom
        self.on_generate, self.on_save_bom = on_generate, on_save_bom
        self.on_add_bom_item, self.on_remove_bom_item = on_add_bom_item, on_remove_bom_item
        self.bom_removable = {}
        self.document_rows, self.on_open_document = document_rows, on_open_document
        self.on_link_document, self.on_unlink_document = on_link_document, on_unlink_document
        self.record, self.revisions, self.currency = None, {}, None
        self.eco_number, self.shown = None, []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL, command=self._tab_changed)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        for name in ("Details", "History", "Uses", "Where used", "BOM", "Documents"):
            self.tabs.add(name)
            self.tabs.tab(name).columnconfigure(0, weight=1)
        self._details_tab(self.tabs.tab("Details"))
        self._history_tab(self.tabs.tab("History"))
        self.reference_trees = {}
        for name, columns in (("Uses", USES_COLUMNS), ("Where used", USED_IN_COLUMNS)):
            self._references_tab(self.tabs.tab(name), name, columns)
        self._bom_tab(self.tabs.tab("BOM"))
        self._documents_tab(self.tabs.tab("Documents"))
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
        self.save_bom_button = release_button.ReleaseButton(bar, text="Save BOM File", width=110, height=28,
                                                            fg_color=theme.ACCENT, hover_color="#18527f",
                                                            command=self._save_bom)
        self.save_bom_button.grid(row=0, column=4, padx=(10, 0))
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
        self.shown = part_details_text.revision_details(self.record, rev, self.revisions, currency=self.currency)
        for number, (label, text) in enumerate(self.shown):
            ctk.CTkLabel(self.fields, text=label + ":", text_color=theme.MUTED, anchor="nw").grid(
                row=number, column=0, sticky="nw", padx=(4, 10), pady=2)
            ctk.CTkLabel(self.fields, text=text, anchor="nw", justify="left", wraplength=self.wrap_width).grid(
                row=number, column=1, sticky="nw", pady=2)       # top-aligned with its label, even wrapped
        self.after_idle(self._wrap)
        self.eco_number, _how = part_details_text.eco_for(self.record, rev)
        if self.eco_number and self.on_view_eco:
            self.eco_button.grid()
        else:
            self.eco_button.grid_remove()
        self._show_documents(rev)
        if self.on_generate and part_details_text.files_flagged(self.record, rev, self.revisions):
            self.generate_button.grid()
        else:
            self.generate_button.grid_remove()
        if self.on_save_bom and part_details_text.bom_flagged(self.record, rev):
            self.save_bom_button.grid()
        else:
            self.save_bom_button.grid_remove()

    def _save_bom(self):
        if self.record is not None and self.on_save_bom:
            self.on_save_bom(self.record.pn)

    def _generate(self):
        if self.record is not None and self.on_generate:
            self.on_generate(self.record.pn)

    def _view_eco(self):
        if self.eco_number and self.on_view_eco:
            self.on_view_eco(self.eco_number)

    # -- Documents -------------------------------------------------------------
    def _documents_tab(self, tab):
        tab.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 4))
        self.documents_label = ctk.CTkLabel(bar, text="", text_color=theme.MUTED, anchor="w")
        self.documents_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        for column, (text, command) in enumerate((("Open", self._open_document), ("Add...", self._link_document),
                                                  ("Remove", self._unlink_document))):
            release_button.ReleaseButton(bar, text=text, width=80, height=28,
                                         fg_color=theme.TEAL if column == 0 else theme.GRAY,
                                         hover_color=theme.TEAL_HOVER if column == 0 else theme.GRAY_HOVER,
                                         command=command).grid(row=1, column=column, padx=(0, 6))
        frame, self.documents_tree, _sorter = make_table(tab, document_text.LINK_COLUMNS, scale=self.scale)
        frame.grid(row=1, column=0, sticky="nsew")
        self.documents_tree.bind("<Double-1>", lambda event: self._open_document())

    def _show_documents(self, rev):
        self.documents_tree.delete(*self.documents_tree.get_children())
        rows = self.document_rows(self.record, rev) if self.document_rows and self.record is not None else []
        for number, values in rows:
            self.documents_tree.insert("", "end", iid=number, values=values)
        linked = f"{len(rows)} linked document{'s' if len(rows) != 1 else ''}" if rows else "no documents linked"
        self.documents_label.configure(text=f"Rev {rev}: {linked}")

    def _chosen_document(self):
        chosen = self.documents_tree.selection()
        return chosen[0] if chosen else None

    def _open_document(self):
        number = self._chosen_document()
        if number and self.on_open_document:
            self.on_open_document(number)

    def _link_document(self):
        if self.on_link_document and self.record is not None:
            self.on_link_document(self.rev_var.get())

    def _unlink_document(self):
        number = self._chosen_document()
        if number and self.on_unlink_document:
            self.on_unlink_document(self.rev_var.get(), number)
        elif self.on_unlink_document:
            self.documents_label.configure(text="Click a document first.")

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
        frame, self.tree, self.sorter = make_table(tab, HISTORY_COLUMNS, scale=self.scale)
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
        frame, tree, _sorter = make_table(tab, columns, scale=self.scale)
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
        self.bom_add = release_button.ReleaseButton(buttons, text="Add item...", width=90, height=28,
                                                    fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                                    command=self._add_bom_item)
        self.bom_add.grid(row=0, column=2, padx=(8, 0))
        self.bom_remove = release_button.ReleaseButton(buttons, text="Remove", width=80, height=28,
                                                       fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                                       command=self._remove_bom_item)
        self.bom_remove.grid(row=0, column=3, padx=(8, 0))
        for button in (self.bom_add, self.bom_remove):
            button.grid_remove()
        self.bom_note = ctk.CTkLabel(tab, text="", text_color=theme.MUTED, anchor="w", justify="left",
                                     wraplength=320)
        self.bom_note.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
        tab.bind("<Configure>", lambda event: self._wrap_bom_note(event.width), add="+")
        frame, self.bom_tree, _sorter = make_table(tab, bom_text.COLUMNS, scale=self.scale)
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

    def _add_bom_item(self):
        if self.on_add_bom_item and self.record is not None:
            self.on_add_bom_item()

    def _remove_bom_item(self):
        stems = [self.bom_removable[iid] for iid in self.bom_tree.selection() if iid in self.bom_removable]
        if stems and self.on_remove_bom_item:
            self.on_remove_bom_item(stems[0])
        elif self.on_remove_bom_item:
            self.bom_note.configure(text="Select a line added by hand first.")

    def show_bom(self, rows=None, note="", can_update=False, editable=False, removable=None):
        """Fill the BOM tab with bom_text.table rows (None: not read yet, and `note` says why). `can_update` shows
        the Update BOM button; `editable` shows Add item... and Remove, which can take off the lines in
        `removable` ({iid: stem}, bom_text.removable)."""
        if can_update and self.on_update_bom:
            self.bom_update.grid()
        else:
            self.bom_update.grid_remove()
        self.bom_removable = dict(removable or {}) if editable else {}
        for button, callback in ((self.bom_add, self.on_add_bom_item), (self.bom_remove, self.on_remove_bom_item)):
            if editable and callback:
                button.grid()
            else:
                button.grid_remove()
        self.bom_tree.delete(*self.bom_tree.get_children())
        for iid, values in rows or []:
            self.bom_tree.insert("", "end", iid=iid, values=values)
        self.bom_note.configure(text=note)

    # -- filling it in -------------------------------------------------------------
    def show(self, record, revisions=None, currency=None):
        """Show a part (a records Record); `revisions` is {revision: [files]}; `currency` the team's (USD), for
        costs."""
        self.record, self.revisions, self.currency = record, revisions or {}, currency
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
