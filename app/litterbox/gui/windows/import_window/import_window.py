"""
import_window.py - the Import window: choose folders, scan, review the proposed part numbers, import.
"""

import queue
import tkinter as tk

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.gui.windows.import_window.cell_editing import CellEditing
from litterbox.gui.windows.import_window.finishing import Finishing
from litterbox.gui.windows.import_window.pick_page import PickPage
from litterbox.gui.windows.import_window.table_page import TablePage
from litterbox.importing import manifest as manifest_module
from litterbox.importing import scan
from litterbox.importing import session as import_session
from litterbox.user import settings
from litterbox.vault import config


class ImportWindow(PickPage, TablePage, CellEditing, Finishing, modal_dialog.ModalDialog):
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
    # Pages, status, background results
    # ------------------------------------------------------------------

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

    def _start_job(self, source, text):
        try:
            self.session.start(self._after(self._prepared), self._progress, manifest_root=settings.ROOT,
                               cots=self.cots, **source)
        except LitterboxError as e:
            self._say(str(e), "warn")
            return
        self._begin(text)























