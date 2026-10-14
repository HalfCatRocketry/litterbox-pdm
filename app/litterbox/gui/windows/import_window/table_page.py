"""
table_page.py - page 2 of the Import window: the table of items, ticks, families, duplicates and
the proposed part numbers.
"""

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui.logic import import_table
from litterbox.gui.logic import list_view
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.importing import import_errors


class TablePage:
    """page 2 of the Import window: the table of items, ticks, families, duplicates and (part of the Import window)."""

    def _build_table_page(self):
        page = self.table_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(6, 6))
        bar.columnconfigure(0, weight=1)
        self.summary = ctk.CTkLabel(bar, text="", anchor="w")
        self.summary.grid(row=0, column=0, sticky="w")
        for column, (text, command) in enumerate((("Select All", lambda: self._tick_all(True)),
                                                  ("Deselect All", lambda: self._tick_all(False)),
                                                  ("Refresh numbers", self._refresh_numbers))):
            release_button.ReleaseButton(bar, text=text, command=command, width=110, height=30, fg_color=theme.GRAY,
                          hover_color=theme.GRAY_HOVER).grid(row=0, column=1 + column, padx=(6, 0))

        family = ctk.CTkFrame(bar, fg_color="transparent")
        family.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        self.family_var = tk.BooleanVar(value=False)
        self.family_box = ctk.CTkCheckBox(family, text="Import all as the same base number:", width=0,
                                          variable=self.family_var, command=self._family_toggled)
        self.family_box.grid(row=0, column=0)
        # No textvariable here: CustomTkinter only shows placeholder text without one (see NewPartDialog).
        self.family_entry = ctk.CTkEntry(family, width=130, height=30, placeholder_text="")
        self.family_entry.grid(row=0, column=1, padx=(8, 0))
        self.family_entry.bind("<Return>", self._family_typed)
        self.family_entry.bind("<FocusOut>", self._family_typed)
        ctk.CTkLabel(family, text="(leave empty for the next free number; if it is in use, new variants start at "
                                  "the lowest free one)", text_color=theme.MUTED).grid(row=0, column=2, padx=(10, 0))

        frame = ctk.CTkFrame(page, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=24)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table_sorting.style_tables()
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        for name, title, width, stretch in self.COLUMNS:
            self.tree.column(name, width=width, anchor="center" if name == "tick" else "w", stretch=stretch)
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w, _s in self.COLUMNS])
        for tag, options in (("ok", {"foreground": "#e6e6e6"}), ("typed", {"foreground": "#6cb6ff"}),
                             ("warn", {"foreground": theme.WARN}), ("off", {"foreground": "#7a7a7a"}),
                             ("conflict", {"foreground": "#ffffff", "background": "#8b3a3a"})):
            self.tree.tag_configure(tag, **options)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._show_detail())

        ctk.CTkLabel(page, text="\u2611 = will be imported.   \u2610 = left out: no part number, nothing copied, and "
                                "it stays in the saved scan so you can import it later.   Click the first column to "
                                "select or deselect (Shift-click selects everything in between).\nDouble-click a part number, name or description to edit it "
                                "(clear a part number to let Litterbox choose one).",
                     text_color=theme.MUTED, anchor="w", justify="left", wraplength=1050).grid(
            row=2, column=0, sticky="ew", padx=26, pady=(6, 0))
        self.detail = ctk.CTkLabel(page, text="", anchor="nw", justify="left", wraplength=1050, height=60,
                                   text_color=theme.MUTED)
        self.detail.grid(row=3, column=0, sticky="ew", padx=26, pady=(2, 0))

    def _check_duplicates(self, then=None):
        """Import COTS: look for rows that duplicate parts already in the vault (a warning, never a block)."""
        def done(found, error):
            self._show("table")
            if error is None:
                self.duplicates = found
                self._rebuild()
                if found:
                    self._say(f"{len(found)} row(s) look like parts the vault already has (yellow). Select a row to "
                              "see why.", "warn")
            else:
                self._say(self._error_text(error), "warn")
            if then:
                then(error is None)
        try:
            self.session.check_duplicates(self._after(done))
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking for parts the vault already has...")

    def _rebuild(self):
        prepared = self.session.prepared
        rows = import_table.import_rows(prepared.candidates, prepared.proposal, self.conflicts, self.duplicates)
        self._details = {str(r.item_id): r for r in rows}
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=str(r.item_id), tags=(r.tag,), values=(
                "☑" if r.ticked else "☐", r.pn, r.name, r.description, r.kind, r.files, r.notes))
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self.summary.configure(text=import_table.import_summary_line(prepared.candidates, prepared.proposal, self.conflicts),
                               text_color=theme.ERROR if self.conflicts else "#e6e6e6")
        self._show_detail()

    def _show_detail(self):
        chosen = self.tree.selection()
        row = self._details.get(chosen[0]) if chosen else None
        self.detail.configure(text=row.detail if row else "")

    def _blocked(self):
        """True (and says why) while a job is running, since the background thread is using the table."""
        if self.running:
            self._say("Please wait for the current step to finish.", "warn")
        return self.running

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if not iid or self._blocked():
            return
        ticked = self._details[iid].ticked
        self._end_edit()
        self.conflicts, self.duplicates = [], {}              # row positions change; the next check finds them again
        anchor, shown = self.last_click, list(self.tree.get_children())
        if list_view.shift_held(event) and anchor is not None and anchor[0] in shown:
            # Shift: give every row from the last click to this one the state the last click gave its row
            between = list_view.range_between(shown, anchor[0], iid)
            self.last_click = (iid, anchor[1])
            self._include_rows([int(i) for i in between], anchor[1])
            return "break"
        self.last_click = (iid, not ticked)
        self._run_quick(lambda done: self.session.include(int(iid), not ticked, done))
        return "break"

    def _tick_all(self, state):
        if self._blocked():
            return
        self._include_rows([r.item_id for r in self._details.values()], state)

    def _include_rows(self, item_ids, state):
        """Select (or deselect) these rows one after another on the session's thread, then redraw."""
        wanted = [self._details[str(i)] for i in item_ids if str(i) in self._details
                  and self._details[str(i)].ticked != state]
        self.conflicts, self.duplicates = [], {}

        def next_one(_result=None, error=None):
            if error is not None:
                self._say(self._error_text(error), "warn")
                if isinstance(error, import_errors.FamilyFull):
                    messagebox.showwarning("Not enough variant numbers", self._error_text(error), parent=self)
            if wanted and error is None:
                row = wanted.pop(0)
                self.running = False
                self._run_quick(lambda done: self.session.include(row.item_id, state, done), next_one, rebuild=False)
            else:
                self.running = False
                self._rebuild()

        next_one()

    def _run_quick(self, start, then=None, rebuild=True):
        """Run a short session job (ticking a row) without switching to the progress view."""
        def done(result, error):
            self.running = False
            if self.closing:
                self._really_close()
                return
            if then is not None:
                then(result, error)
                return
            if error is not None:
                self._say(self._error_text(error), "warn")
                if isinstance(error, import_errors.FamilyFull):
                    messagebox.showwarning("Not enough variant numbers", self._error_text(error), parent=self)
            if rebuild:
                self._rebuild()
        self.running = True
        try:
            start(done)
        except LitterboxError as e:
            self.running = False
            self._say(str(e), "warn")

    def _family_toggled(self):
        """The 'same base number' box was ticked or cleared."""
        if self.running:
            self.family_var.set(not self.family_var.get())          # the table is busy: undo the click
            self._say("Please wait for the current step to finish.", "warn")
            return
        self._end_edit()
        self._apply_family(self.family_entry.get().strip() or self.family_placeholder if self.family_var.get() else None)

    def _family_typed(self, event=None):
        """A base number was typed (Return, or the box lost focus): use it if the box is ticked."""
        if not self.family_var.get() or self.running or self.closed:
            return
        wanted = self.family_entry.get().strip() or self.family_placeholder
        if self.family_applied is None or str(self.family_applied).lstrip("0") != wanted.lstrip("0"):
            self._apply_family(wanted)

    def _apply_family(self, base):
        """Give the rows variants of `base` (None: separate numbers again). Refuses, and says why, if it won't fit."""
        def done(proposal, error):
            self.running = False
            if self.closing:
                self._really_close()
                return
            if error is not None:
                self.family_var.set(self.family_applied is not None)       # nothing changed: go back
                self._say(self._error_text(error), "warn")
                messagebox.showwarning("Part number", self._error_text(error), parent=self)
                return
            self.family_applied = base
            self.conflicts, self.duplicates = [], {}
            self._rebuild()
            if base is None:
                self._say("The rows have separate part numbers again.")
            else:
                self._say(f"All the rows are variants of {base}: any rows you typed numbers into were left alone.")
        self.running = True
        try:
            self.session.set_family(base, done)
        except LitterboxError as e:
            self.running = False
            self.family_var.set(self.family_applied is not None)
            self._say(str(e), "warn")

    def _refresh_numbers(self):
        if self._blocked():
            return
        self._end_edit()

        def done(state, error):
            if error is not None:
                self._show("table")
                self._say(self._error_text(error), "error")
                return
            self._show("table")
            self.duplicates = {}
            self.conflicts, self.renumbered = state.conflicts, state.renumbered + self.renumbered
            self._rebuild()
            if state.conflicts:
                self._say(f"{len(state.conflicts)} part number(s) you typed are taken. Change the red rows.", "error")
            elif state.renumbered:
                self._say(f"{len(state.renumbered)} automatic part number(s) were taken and have been replaced.", "warn")
            else:
                self._say("All the part numbers are available.", "good")

        try:
            self.session.refresh(self._after(done))
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking the part numbers against the newest records...")
