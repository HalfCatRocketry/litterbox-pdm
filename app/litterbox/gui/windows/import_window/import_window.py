"""
import_window.py - the Import window: choose folders, scan, review the proposed part numbers, import.
"""

import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from litterbox.core import part_number
from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import error_text
from litterbox.gui.logic import import_table
from litterbox.gui.logic import list_view
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import pn_editor
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.importing import import_errors
from litterbox.importing import manifest as manifest_module
from litterbox.importing import scan
from litterbox.importing import session as import_session
from litterbox.user import settings
from litterbox.vault import config


class ImportWindow(ctk.CTkToplevel):
    """The Import window: choose folders, review the table, Finish & Import.

        ImportWindow(parent, repo, org, on_imported=callback, log=function)

    1. Pick folders (or open a saved scan). Litterbox scans them (read-only), reads what each
       assembly references, and proposes new part numbers.
    2. The table lists every item with its new part number, name and description. Click the
       first column to select / deselect an item. Double-click a part number, name or description to
       edit it. Clear a part number to let Litterbox choose one again.
    3. Finish & Import checks the numbers against the newest records and imports. If a number you
       typed has been taken, nothing is imported: the window stays on the table with those rows
       in red. Cancel at any time removes everything copied so far.

    All the work is done by import_session.ImportSession on a background thread; this window
    only shows things and passes on clicks. The pieces that decide what rows say and what
    an edit does are in gui_logic.py.
    """

    COLUMNS = (("tick", "", 36, False), ("pn", "New part number", 140, False), ("name", "Name", 230, True),
               ("description", "Description", 260, True), ("kind", "Type", 90, False),
               ("files", "Files", 110, False), ("notes", "Notes", 230, True))
    EDIT_COLUMNS = {"#2": "pn", "#3": "name", "#4": "description"}

    def __init__(self, parent, repo, org, on_imported=None, log=None, cots=False):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        try:
            config.apply(repo)                      # learn this vault's digit counts for the part number boxes
        except config.ConfigError:
            pass
        self.repo, self.org, self.on_imported = repo, org, on_imported
        self.cots = cots                            # Import COTS: everything is recorded as a purchased part
        self.last_click = None                      # (row id, ticked afterwards) for shift-click
        self.family_applied = None                  # the base number the rows were last given, if any
        self.family_placeholder = ""
        self.duplicates = {}                        # table row -> warnings about parts the vault already has
        self._cots_confirmed = False
        self.heading = "Import COTS" if cots else "Import CAD"
        self.inbox = queue.Queue()                  # results from the background thread
        self.session = import_session.ImportSession(repo, self.inbox.put, log=log or (lambda text: None), org=org)
        self.folders = []
        self.conflicts = []
        self.renumbered = []
        self.running = False
        self.finishing = False
        self.closing = False
        self.closed = False
        self.editor = None
        self._details = {}                          # table row id -> gui_logic.ImportRow

        width, height = 1140, 720
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(self.heading)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(900, 560)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        ctk.CTkLabel(header, text=self.heading, font=ctk.CTkFont(size=22, weight="bold"), anchor="w").pack(anchor="w")
        ctk.CTkLabel(header, text=("For purchased parts you have not modified (McMaster-Carr, vendor models). "
                                   "They are recorded as COTS. Your original files are only read."
                                   if cots else
                                   "Your original files are only read. Litterbox copies them into the vault under "
                                   "new part numbers."), text_color=theme.MUTED, anchor="w").pack(anchor="w")

        self.pick_page = ctk.CTkFrame(self, fg_color="transparent")
        self.table_page = ctk.CTkFrame(self, fg_color="transparent")
        self._build_pick_page()
        self._build_table_page()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 16))
        footer.columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(footer, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=width - 60)
        self.status.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.progress = ctk.CTkProgressBar(footer)
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.secondary = release_button.ReleaseButton(buttons, text="Close", width=150, height=38, fg_color=theme.GRAY,
                                       hover_color=theme.GRAY_HOVER, command=self._close)
        self.secondary.grid(row=0, column=0, padx=(0, 10))
        self.primary = release_button.ReleaseButton(buttons, text="Scan & Review", width=200, height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._scan)
        self.primary.grid(row=0, column=1)

        self.mode = "pick"
        self._show("pick")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._pump)
        self.after(150, self._grab)

    # ------------------------------------------------------------------
    # Building the pages
    # ------------------------------------------------------------------
    def _build_pick_page(self):
        page = self.pick_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ctk.CTkLabel(page, text="Folders to import (everything inside them is included)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=24, pady=(10, 4))
        self.folder_list = tk.Listbox(page, bg=theme.BG_PANEL, fg="#e6e6e6", selectbackground=theme.ACCENT, borderwidth=0,
                                      highlightthickness=0, font=("Segoe UI", 10), activestyle="none")
        self.folder_list.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 8))
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.grid(row=2, column=0, sticky="w", padx=24, pady=(0, 8))
        for column, (text, command) in enumerate((("Add folder...", self._add_folder),
                                                  ("Remove selected", self._remove_folder),
                                                  ("Open a saved scan...", self._open_manifest))):
            release_button.ReleaseButton(row, text=text, command=command, height=34, fg_color=theme.GRAY,
                          hover_color=theme.GRAY_HOVER).grid(row=0, column=column, padx=(0 if column == 0 else 8, 0))
        ctk.CTkLabel(page, text="Scanning looks at file names only. Nothing is opened, changed or moved."
                                + ("" if self.cots else " Purchased (COTS) parts are brought in with Import COTS."),
                     text_color=theme.MUTED, anchor="w", justify="left", wraplength=900).grid(
            row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        self.cots_var = tk.BooleanVar(value=False)
        if self.cots:
            ctk.CTkCheckBox(page, text="I confirm that every file in these folders is a purchased part that I have "
                                       "NOT modified.", variable=self.cots_var, width=60).grid(
                row=4, column=0, sticky="w", padx=24, pady=(4, 6))

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

    # ------------------------------------------------------------------
    # Pages, status, background results
    # ------------------------------------------------------------------
    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _show(self, mode):
        """mode: 'pick' (choose folders), 'table' (review), or 'working' (a job is running)."""
        self.mode = mode
        shown = "table" if mode == "table" or (mode == "working" and self.session.prepared is not None) else "pick"
        self.pick_page.grid_forget()
        self.table_page.grid_forget()
        (self.table_page if shown == "table" else self.pick_page).grid(row=1, column=0, sticky="nsew")
        working = mode == "working"
        if working:
            self.progress.grid()
            self.primary.configure(state="disabled")
            self.secondary.configure(text="Cancel import" if self.finishing else "Cancel", state="normal",
                                     command=self._cancel_job)
        else:
            self.progress.grid_remove()
            self.progress.set(0)
            self.secondary.configure(text="Close" if mode == "pick" else "Cancel import", state="normal",
                                     command=self._close)
            if mode == "pick":
                self.primary.configure(text="Scan & Review", state="normal", command=self._scan)
            else:
                self.primary.configure(text="Finish & Import", state="normal", command=self._finish)

    def _say(self, text, tone="normal"):
        color = {"normal": theme.MUTED, "warn": theme.WARN, "error": theme.ERROR, "good": theme.GREEN_TEXT}[tone]
        self.status.configure(text=text, text_color=color)

    def _pump(self):
        """Run the results the background thread has queued (always on the window's own thread)."""
        if self.closed:
            return
        try:
            while True:
                work = self.inbox.get_nowait()
                try:
                    work()
                except Exception as e:                  # a bug here must not freeze the window
                    self._say(f"Something unexpected went wrong: {e!r}", "error")
                    self.running = False
        except queue.Empty:
            pass
        try:
            self.after(50, self._pump)
        except tk.TclError:
            pass

    def _begin(self, text, finishing=False):
        self.running, self.finishing = True, finishing
        self._end_edit()
        self.progress.set(0)
        self._say(text)
        self._show("working")

    def _progress(self, done, total, text):
        if total:
            self.progress.set(min(done / total, 1.0))
        self._say(text)

    def _after(self, handler):
        """Wrap a result handler: ignore it if the window is closing, else mark the job finished first."""
        def wrapper(result, error):
            self.running = False
            self.finishing = False
            if self.closing:
                self._really_close()
                return
            handler(result, error)
        return wrapper

    @staticmethod
    def _error_text(error):
        known = (LitterboxError, scan.ScanError, manifest_module.ManifestError)
        return str(error) if isinstance(error, known) else f"Unexpected error: {error!r}"

    # ------------------------------------------------------------------
    # Page 1: choosing folders and scanning
    # ------------------------------------------------------------------
    def _add_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Folder with CAD files to import")
        if folder and folder not in self.folders:
            self.folders.append(folder)
            self.folder_list.insert("end", folder)

    def _remove_folder(self):
        for index in reversed(self.folder_list.curselection()):
            self.folder_list.delete(index)
            del self.folders[index]

    def _cots_ok(self):
        """Import COTS only starts once the user has ticked the confirmation box."""
        if self.cots and not self.cots_var.get():
            self._say("Tick the box to confirm that everything you are importing is a purchased, unmodified part.",
                      "warn")
            return False
        return True

    def _scan(self):
        if not self._cots_ok():
            return
        if not self.folders:
            self._say("Add at least one folder first.", "warn")
            return
        self._start_job(dict(folders=list(self.folders)), "Scanning...")

    def _open_manifest(self):
        path = filedialog.askopenfilename(parent=self, title="Open a saved scan",
                                          initialdir=str(settings.ROOT / "imports"),
                                          filetypes=[("Litterbox scan", "*.yaml *.yml"), ("All files", "*.*")])
        if path and self._cots_ok():
            self._start_job(dict(manifest_path=path), "Opening the saved scan...")

    def _start_job(self, source, text):
        try:
            self.session.start(self._after(self._prepared), self._progress, manifest_root=settings.ROOT,
                               cots=self.cots, **source)
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin(text)

    def _prepared(self, proposal, error):
        if error is not None:
            self._show("pick")
            if isinstance(error, import_errors.ImportCancelled):
                self._say("Cancelled. Nothing was changed.", "warn")
            else:
                self._say("The scan could not be completed.", "error")
                messagebox.showerror("Import CAD", error_text.shorten(self._error_text(error)), parent=self)
            return
        self.conflicts, self.renumbered = [], []
        self.family_applied = None
        self.family_var.set(False)
        self.family_placeholder = number_input.import_base_placeholder(self.repo, self.session.prepared.proposal.org)
        self.family_entry.configure(placeholder_text=self.family_placeholder)
        self._show("table")
        self._rebuild()
        self._say(f"Scan saved to {self.session.manifest_path}. Review the table, then press Finish & Import.\n"
                  + self.session.prepared.proposal.note)
        if self.cots:
            self._check_duplicates()

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

    # ------------------------------------------------------------------
    # Page 2: the table
    # ------------------------------------------------------------------
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

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        column = self.EDIT_COLUMNS.get(self.tree.identify_column(event.x))
        iid = self.tree.identify_row(event.y)
        if not column or not iid or self._blocked():
            return
        self._end_edit()
        box = self.tree.bbox(iid, self.tree.identify_column(event.x))
        if not box:
            return
        x, y, w, h = box
        if column == "pn":
            base, variant = self._pn_parts(iid)
            editor = pn_editor.PnEditor(self.tree, self.org, base, variant, self._commit_edit, self._end_edit)
            editor.place(x, y, max(w, 200), h)
        else:
            editor = tk.Entry(self.tree, font=("Segoe UI", 10), bg="#1f1f1f", fg="#ffffff",
                              insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightcolor=theme.ACCENT)
            editor.insert(0, self.tree.set(iid, column))
            editor.select_range(0, "end")
            editor.place(x=x, y=y, width=w, height=h)
            editor.focus_set()
            editor.bind("<Return>", lambda e: self._commit_edit())
            editor.bind("<Escape>", lambda e: self._end_edit())
            editor.bind("<FocusOut>", lambda e: self._commit_edit())
        self.editor = (editor, iid, column)
        return "break"

    def _pn_parts(self, iid):
        """The row's current part number as the two box texts ('00042', '001'), or empty boxes if unticked."""
        text = self.tree.set(iid, "pn")
        parsed = parse_pn(text) if text else None
        if not parsed:
            return "", ""
        return part_number.format_base(parsed.base), part_number.format_variant(parsed.variant)

    def _end_edit(self):
        if self.editor:
            editor, _iid, _column = self.editor
            self.editor = None
            try:
                editor.destroy()
            except tk.TclError:
                pass

    def _commit_edit(self):
        if not self.editor:
            return
        editor, iid, column = self.editor
        text = editor.get()
        self._end_edit()
        prepared = self.session.prepared
        index = next((n for n, e in enumerate(prepared.proposal.entries) if e.item.id == int(iid)), None)
        if column == "pn":
            problem = import_table.edit_import_pn(prepared, int(iid), text[0], text[1], repo=self.repo)
        else:
            problem = import_table.edit_import_cell(prepared, int(iid), column, text)
        self._say(problem, "warn" if problem else "normal")
        if column == "pn" and not problem:                    # an edited number is no longer known to be taken
            self.conflicts = [c for c in self.conflicts if c.index != index]
        self._rebuild()

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

    # ------------------------------------------------------------------
    # Finish & Import, cancel, close
    # ------------------------------------------------------------------
    def _finish(self):
        if self._blocked():
            return
        self._end_edit()
        self.conflicts = []
        if self.cots and not self._cots_confirmed:
            self._check_duplicates(then=self._confirm_cots)       # look for duplicates, then ask
            return
        try:
            self.session.finish(self._after(self._finished), self._progress)
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin("Checking the part numbers...", finishing=True)

    def _confirm_cots(self, checked):
        """The last question before Import COTS goes ahead: it names the duplicates found, if any."""
        if not checked:
            return
        entries = self.session.prepared.proposal.entries
        text = import_table.import_cots_confirm_text(len(entries), self.duplicates, [e.name for e in entries])
        if messagebox.askyesno("Import as COTS?", text, parent=self):
            self._cots_confirmed = True
            self._finish()
        else:
            self._say("Nothing was imported.", "warn")

    def _finished(self, result, error):
        confirmed, self._cots_confirmed = self._cots_confirmed, False      # each Finish asks again
        self.session.set_allow_external(False)             # the answer to the question below counts for one try only
        if isinstance(error, import_errors.ExternalReferences):
            self._show("table")
            self._rebuild()
            if messagebox.askyesno("Files outside this import", import_table.import_external_text(error), parent=self):
                self.session.set_allow_external(True)
                self._cots_confirmed = confirmed
                self._finish()
            else:
                self._say("Nothing was imported. Select the missing items, or scan their folder too, and try again.",
                          "warn")
            return
        if error is None:
            messagebox.showinfo("Import complete", import_table.import_result_text(result), parent=self)
            if self.on_imported:
                self.on_imported(result)
            self._really_close()
            return
        self._show("table")
        if isinstance(error, import_errors.PNConflict):
            self.conflicts, self.renumbered = error.conflicts, error.renumbered
            self._rebuild()
            self._say("Nothing was imported: some part numbers can't be used. Change the red rows, then press "
                      "Finish & Import again.", "error")
            messagebox.showwarning("Part numbers taken", import_table.import_conflict_text(error.conflicts, error.renumbered),
                                   parent=self)
        elif isinstance(error, import_errors.ImportCancelled):
            self._rebuild()
            self._say("Import cancelled. Nothing was added to the vault, and your files were not changed.", "warn")
        else:
            self._rebuild()
            self._say("The import did not go ahead, and nothing was added to the vault.", "error")
            messagebox.showerror("Import CAD", error_text.shorten(self._error_text(error)), parent=self)

    def _cancel_job(self):
        if self.running:
            self.session.cancel()
            self.secondary.configure(state="disabled")
            self._say("Cancelling... removing anything already copied.", "warn")

    def _close(self):
        if self.running:
            if messagebox.askyesno("Import CAD", "Cancel the import in progress? Anything already copied will be "
                                                 "removed.", parent=self):
                self.closing = True
                self._cancel_job()
            return
        if self.mode == "table" and self.session.prepared and messagebox.askyesno(
                "Import CAD", "Close without importing? Nothing has been added to the vault. The scan stays saved "
                              "and can be opened again.", parent=self) is False:
            return
        self._really_close()

    def _really_close(self):
        if self.closed:
            return
        self.closed = True
        self._end_edit()
        try:
            self.session.close()
        finally:
            try:
                self.grab_release()
            except tk.TclError:
                pass
            self.destroy()
