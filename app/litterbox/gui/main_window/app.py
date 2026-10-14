"""
app.py - the main Litterbox window (App).
"""

import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox import diagnostics
from litterbox import version
from litterbox.cad import opener
from litterbox.core import part_number
from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError, NothingToSaveError
from litterbox.git import read_only
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import clone_dialog
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.dialogs import edit_details_dialog
from litterbox.gui.dialogs import error_details
from litterbox.gui.dialogs import filename_dialog
from litterbox.gui.dialogs import new_part_dialog
from litterbox.gui.dialogs import org_dialog
from litterbox.gui.dialogs import revision_picker
from litterbox.gui.dialogs import text_input
from litterbox.gui.dialogs import vault_settings_dialog
from litterbox.gui.dialogs.team import person_dialog
from litterbox.gui.dialogs.team import roles_dialog
from litterbox.gui.dialogs.workflow import reassign_dialog
from litterbox.gui.dialogs.workflow import request_dialog
from litterbox.gui.dialogs.workflow import workflows_dialog
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import confirmations
from litterbox.gui.logic import error_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import icon_files
from litterbox.gui.logic import job_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import opening_text
from litterbox.gui.logic import org_menu
from litterbox.gui.logic import reference_text
from litterbox.gui.logic import task_text
from litterbox.gui.logic import team_text
from litterbox.gui.logic import workflow_editor
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.gui.windows import history_window
from litterbox.gui.windows import references_window
from litterbox.gui.windows import tasks_window
from litterbox.gui.windows import team_window
from litterbox.gui.windows.import_window import import_window
from litterbox.jobs import job_queue as jobs
from litterbox.parts import cancel_revision
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import create
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import part_changes
from litterbox.parts import part_details
from litterbox.parts import part_status
from litterbox.parts import planning
from litterbox.parts import revise
from litterbox.parts import undoing
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import reference_model
from litterbox.references import reference_queries
from litterbox.references import reference_reader
from litterbox.references import reference_replace
from litterbox.references import reference_rescan
from litterbox.team import team_editing
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.user import settings
from litterbox.user import updater
from litterbox.vault import clone as vault_clone
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.vault import create_vault
from litterbox.vault import settings_admin as vault_settings
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates


# Set to True to download the latest changes every time the app opens.
# (Off by default: a download can replace files that are open in SolidWorks.)
AUTO_GET_LATEST_ON_START = False


class App(ctk.CTk):
    identity = team_identity.Identity(team_identity.LEGACY)       # replaced after the first refresh

    def __init__(self):
        super().__init__()
        # Icon first, and keep the window hidden until it is fully built, so the user
        # never sees it half-ready or with the wrong icon. (CustomTkinter supports
        # calling withdraw() right after creating the window.)
        self.settings = settings.load()
        settings.DEBUG = diagnostics.DEBUG = settings.is_debug(self.settings)
        if org_menu.migrate_settings(self.settings, self._detect_org):
            settings.save(self.settings)
        self.org = org_menu.current_org(self.settings)
        window_chrome.ICON_SETTING["choice"] = self.settings.get("icon", icon_files.DEFAULT_ICON)
        window_chrome.set_window_icon(self, main_window=True)
        self.withdraw()
        self.title(f"Litterbox {version.display()}")
        self.geometry("1100x740")
        self.minsize(1000, 600)

        self.queue = queue.Queue()      # messages from the background thread to the window
        # Every task runs here, one at a time, in the background (see job_queue.py). The window stays usable meanwhile.
        self.jobs = jobs.JobQueue(deliver=lambda outcome: self.queue.put(("done", outcome)))
        self._was_busy = False
        self._shown_pending = {}
        self.rows = []                  # every PartStatus from the engine
        self.identity = team_identity.Identity(team_identity.LEGACY)      # who you are on this vault's team (see people.py)
        self.rows_by_pn = {}
        self.buttons = []               # disabled while something is running
        self.action_buttons = {}        # button text -> button, for the ones that follow the selection
        self.pending_select = None      # a part to select once the list reloads (the one just created)
        self.note = ""                  # what just happened, kept in the status line after a refresh

        # Everything the engine logs ("> git lfs lock ...") shows up in the log box.
        diagnostics.LOG = lambda message: self.queue.put(("log", message))

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda event: self.refresh())
        self.after(100, self._poll_queue)
        if settings.DEBUG:
            self._watch_for_freezes()

        if self.org and Path(self.repo()).is_dir():
            if AUTO_GET_LATEST_ON_START:
                self.get_latest()
            else:
                self.refresh()
        elif self.org:
            self._say(f"The vault folder for {self.org} wasn't found: {self.repo()}. Use Org setup to fix it.", "warn")
        else:
            self._say("Choose Add org... in the box next to the title to get started.", "warn")

        self.after(120, self._reveal)
        self.after(4000, self._start_update_check)

    # ------------------------------------------------------------------
    # Updates (see updater.py)
    # ------------------------------------------------------------------
    def _start_update_check(self):
        """On start-up, quietly look for a newer release. Only the installed program does; never blocks the window."""
        if not (version.is_installed_build() and updater.configured() and settings.update_check_enabled(self.settings)):
            return

        def work():
            try:
                self.queue.put(("update", updater.find_update()))
            except updater.UpdateError as e:                  # offline, or nothing to offer: stay quiet
                self.queue.put(("log", f"Update check: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def check_for_updates(self):
        """The 'check for updates' button: same check, but says what it found."""
        if not version.is_installed_build():
            messagebox.showinfo("Litterbox", "This copy is running from the source files, so it doesn't update "
                                "itself. The installed program checks GitHub for new releases.")
            return
        if not updater.configured():
            messagebox.showinfo("Litterbox", "This build isn't set up to check for updates.")
            return

        def work():
            try:
                return updater.find_update()
            except updater.UpdateError as e:
                raise LitterboxError(str(e))

        def show(update):
            if update is None:
                messagebox.showinfo("Litterbox", f"You have the newest version ({version.VERSION}).")
            else:
                self._offer_update(update)

        self.run_task(work, "Checked for updates", on_success=show, refresh=False)

    def _offer_update(self, update):
        if update is None:
            return
        notes = f"\n\n{update.notes}" if update.notes else ""
        if messagebox.askyesno("Litterbox update", f"Litterbox {update.version} is available. You have "
                               f"{version.VERSION}.{notes}\n\nUpdate now? Litterbox will close, update and "
                               "start again. Your settings and vault are not touched."):
            self.install_update(update)

    def install_update(self, update):
        def work():
            try:
                return updater.download(update)
            except updater.UpdateError as e:
                raise LitterboxError(str(e))

        self.run_task(work, "Downloaded the update", on_success=self._run_installer, refresh=False)

    def _run_installer(self, path):
        try:
            updater.launch_installer(path)
        except updater.UpdateError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        self._say("Updating... Litterbox will start again by itself.")
        self.after(500, self.destroy)               # the installer replaces the program's files once we've closed

    def _reveal(self):
        """Show the window now that the icon is set and everything is built."""
        self.deiconify()
        self.lift()

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------
    def _button(self, parent, text, command, **options):
        button = release_button.ReleaseButton(parent, text=text, command=command, **options)
        self.buttons.append(button)
        if text in action_rules.BUTTON_ACTIONS:
            self.action_buttons[text] = button
        return button

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header and vault folder
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 6))
        header.columnconfigure((0, 2), weight=1)
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_row, text="Litterbox", font=ctk.CTkFont(size=26, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.org_var = tk.StringVar(value=self.org or "No org")
        self.org_menu = ctk.CTkOptionMenu(
            title_row, variable=self.org_var, values=org_menu.org_menu_values(self.settings), width=120,
            height=32, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
            command=self.on_org_chosen)
        self.org_menu.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.buttons.append(self.org_menu)
        who_box = ctk.CTkFrame(header, fg_color="transparent")
        who_box.grid(row=0, column=2, rowspan=3, sticky="ne")
        self.identity_label = ctk.CTkLabel(who_box, text="", text_color=theme.MUTED, anchor="e")
        self.identity_label.grid(row=0, column=0, padx=(0, 10))
        self.tasks_button = self._button(who_box, "My Tasks", self.show_tasks, width=100, height=30, fg_color=theme.GRAY,
                                         hover_color=theme.GRAY_HOVER)
        self.tasks_button.grid(row=0, column=1, padx=(0, 6))
        team_button = self._button(who_box, "Team...", self.show_team, width=90, height=30, fg_color=theme.GRAY,
                                   hover_color=theme.GRAY_HOVER)
        team_button.grid(row=0, column=2)
        for button in (team_button, self.tasks_button):
            self.buttons.remove(button)         # opening these windows only reads, so they work while busy
        self.update_button = ctk.CTkButton(
            who_box, text=f"Version {version.display()}  -  check for updates", width=0, height=22, fg_color="transparent",
            hover_color=theme.GRAY_HOVER, text_color=theme.MUTED, font=ctk.CTkFont(size=11), command=self.check_for_updates)
        self.update_button.grid(row=1, column=0, columnspan=3, sticky="e", pady=(4, 0))
        ctk.CTkLabel(header, text="Shared vault check-in / check-out", text_color=theme.MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w")
        self.folder_label = ctk.CTkLabel(header, text=self.repo(), text_color=theme.MUTED, anchor="w")
        self.folder_label.grid(row=2, column=0, sticky="w", pady=(2, 0))

        # The status banner: green Ready / yellow Working / red Error (see job_queue.py). A compact box in the middle
        # of the header, between the title and the person's own buttons.
        self.banner = ctk.CTkFrame(header, corner_radius=10, width=280, height=78, fg_color=theme.GREEN)
        self.banner.grid(row=0, column=1, rowspan=3, padx=24)
        self.banner.grid_propagate(False)
        self.banner.columnconfigure(0, weight=1)
        self.banner_title = ctk.CTkLabel(self.banner, text="Ready", font=ctk.CTkFont(size=24, weight="bold"),
                                         text_color="white", anchor="w")
        self.banner_title.grid(row=0, column=0, padx=(16, 4), pady=(8, 0), sticky="w")
        self.banner_detail = ctk.CTkLabel(self.banner, text="", text_color="white", anchor="nw", justify="left",
                                          wraplength=248, font=ctk.CTkFont(size=11))
        self.banner_detail.grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 6), sticky="nw")
        self.banner_details_button = ctk.CTkButton(self.banner, text="Details...", width=76, height=26,
                                                   fg_color="white", text_color=theme.RED, hover_color="#e8e8e8",
                                                   command=self.show_errors)
        self.banner_dismiss_button = ctk.CTkButton(self.banner, text="Dismiss", width=66, height=26,
                                                   fg_color="transparent", border_width=1, border_color="white",
                                                   text_color="white", hover_color=theme.RED_HOVER,
                                                   command=self.dismiss_errors)

        # Search, filters, refresh
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 8))
        toolbar.columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Search part number, name or description...", height=34)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda event: self._render())
        self.view = ctk.CTkSegmentedButton(toolbar, values=list(list_view.VIEWS), command=lambda value: self._render())
        self.view.set("All")
        self.view.grid(row=0, column=1, padx=(0, 8))
        self.void_box = ctk.CTkCheckBox(toolbar, text="Show void", command=self._render, width=90)
        self.void_box.grid(row=0, column=2, padx=(0, 8))
        self.deselect_button = ctk.CTkButton(toolbar, text="Deselect All", width=96, height=34, fg_color=theme.GRAY,
                                             hover_color=theme.GRAY_HOVER, command=self._deselect_all)
        self.deselect_button.grid(row=0, column=3, padx=(0, 8))
        self._button(toolbar, "Refresh", self.refresh, width=84, height=34,
                     fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER).grid(row=0, column=4, padx=(0, 8))
        self._button(toolbar, "Get Latest", self.get_latest, width=100, height=34,
                     fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER).grid(row=0, column=5)

        # The list of parts
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table_sorting.style_tables()
        self.tree = ttk.Treeview(frame, columns=("tick", "pn", "name", "description", "cots", "rev", "state", "files"),
                                 show="headings", selectmode="browse",
                                 style="Parts.Treeview")
        main_columns = (("pn", "Part number", 140, False),
                        ("name", "Name", 240, True),
                        ("description", "Description", 220, True),
                        ("cots", "COTS", 60, False),
                        ("rev", "Rev", 50, False),
                        ("state", "Status", 230, False),
                        ("files", "Files", 110, False))
        for name, title, width, stretch in main_columns:
            self.tree.column(name, width=width, anchor="w", stretch=stretch)
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w, _s in main_columns])
        # The tick boxes: tick parts to act on several at once without worrying about the highlight.
        self.ticked = set()
        self.tree.column("tick", width=40, minwidth=40, anchor="center", stretch=False)
        self.tree.heading("tick", text=list_view.TICK_OFF, anchor="center", command=self._toggle_all_ticks)
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<space>", self._tick_highlighted)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons(), add="+")
        for kind, color in theme.ROW_COLORS.items():
            self.tree.tag_configure(kind, foreground=color)
        self.tree.tag_configure("busy", foreground=theme.BANNER_YELLOW)
        self.tree.tag_configure("ticked", background=theme.TICK_BG)       # last, so it wins for the background only
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", self.show_history)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        # Everyday buttons
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        row1.columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="a")
        big = ctk.CTkFont(size=14, weight="bold")
        for column, (text, command, color, hover) in enumerate((
            ("Check Out", self.check_out, theme.ACCENT, "#18527f"),
            ("Check In", self.check_in, theme.GREEN, theme.GREEN_HOVER),
            ("Save Progress", self.save_progress, theme.TEAL, theme.TEAL_HOVER),
            ("Undo Checkout", self.undo_checkout, theme.RED, theme.RED_HOVER),
            ("Open", self.open_part, theme.TEAL, theme.TEAL_HOVER),
            ("Open Drawing", self.open_drawing, theme.TEAL, theme.TEAL_HOVER),
        )):
            self._button(row1, text, command, height=42, font=big, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 6, 0 if column == 5 else 6))

        # Making parts
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 6))
        row2.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("New Part", self.new_part, theme.ACCENT, "#18527f"),
            ("Import...", self.import_cad, theme.TEAL, theme.TEAL_HOVER),
            ("Import COTS...", self.import_cots, theme.TEAL, theme.TEAL_HOVER),
            ("Edit Details", self.edit_details, theme.ACCENT, "#18527f"),
            ("References...", self.show_references, theme.TEAL, theme.TEAL_HOVER),
        )):
            self._button(row2, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 4 else 4))

        # A part's life: release, revise, and the less common changes
        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 8))
        row3.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("Release", self.release, theme.PURPLE, theme.PURPLE_HOVER),
            ("Revise", self.revise, theme.PURPLE, theme.PURPLE_HOVER),
            ("Cancel Revision", self.cancel_revision, theme.GRAY, theme.GRAY_HOVER),
            ("Make COTS", self.make_cots, theme.TEAL, theme.TEAL_HOVER),
            ("Unrelease", self.reopen, theme.GRAY, theme.GRAY_HOVER),
            ("Void", self.void, theme.GRAY, theme.GRAY_HOVER),
            ("History", self.show_history, theme.GRAY, theme.GRAY_HOVER),
        )):
            self._button(row3, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 6 else 4))

        # Status line and log
        self.status = ctk.CTkLabel(self, text="Ready", text_color=theme.MUTED, anchor="w")
        self.status.grid(row=6, column=0, sticky="ew", padx=26)
        self.log_box = ctk.CTkTextbox(self, height=110, fg_color=theme.BG_PANEL, text_color=theme.MUTED,
                                      font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=7, column=0, sticky="ew", padx=24, pady=(4, 20))
        self.log_box.configure(state="disabled")

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def repo(self):
        """The vault folder of the org that is open."""
        return org_menu.known_orgs(self.settings).get(self.org, "") if self.org else ""

    @staticmethod
    def _detect_org(folder):
        try:
            return config.get_org(folder)
        except Exception:
            return None

    def _reload_org_menu(self):
        self.org_menu.configure(values=org_menu.org_menu_values(self.settings))
        self.org_var.set(self.org or "No org")
        self.folder_label.configure(text=self.repo())

    def on_org_chosen(self, choice):
        """The dropdown changed: switch org (everything reloads) or open the setup pop-up."""
        if choice == org_menu.ADD_ORG:
            self.add_org()
        elif choice == org_menu.CREATE_VAULT:
            self.create_vault()
        elif choice == org_menu.EDIT_ORG:
            self._org_setup(self.org)
        elif choice != self.org:
            self.switch_org(choice)
        self._reload_org_menu()

    def switch_org(self, org):
        self.org = org
        self.settings["last_org"] = org
        self.settings["repo"] = self.repo()
        settings.save(self.settings)
        self.rows, self.rows_by_pn, self.note = [], {}, ""
        self._render()                              # clear the list straight away
        self.folder_label.configure(text=self.repo())
        if Path(self.repo()).is_dir():
            self.refresh()
        else:
            self._say(f"The vault folder for {org} wasn't found: {self.repo()}. Use Org setup to fix it.", "warn")

    def add_org(self):
        """Add org...: paste the URL of a vault on your Git host. Litterbox clones it into its own folder (see
        vault_clone.py), reads the org code and numbering from it, and opens it. A brand-new vault is made with
        Create new vault... instead."""
        known = org_menu.known_orgs(self.settings)
        url = clone_dialog.CloneDialog(self, settings.ROOT).show()
        if not url:
            return
        target, problem = org_menu.plan_add_org(url, settings.ROOT, known)
        if problem:
            messagebox.showwarning("Add org", problem, parent=self)
            return

        def work():
            if target.exists():
                org, _problem = org_menu.inspect_vault_folder(target)
                if org:
                    return target                              # cloned already (an earlier try): just use it
                if any(target.iterdir()):
                    raise LitterboxError(f"{target} already exists and isn't a vault. Rename or remove it, "
                                                "then try again.")
            vault_clone.clone(url.strip(), target)
            try:
                read_only.enforce_read_only(target)
            except LitterboxError as e:
                diagnostics.LOG(f"WARNING: could not set the files read-only: {e}")
            return target

        def cloned(folder):
            org, problem = org_menu.inspect_vault_folder(folder)
            if problem:
                messagebox.showwarning("Add org", f"The vault was copied to {folder}, but:\n\n{problem}",
                                       parent=self)
                return
            org_menu.remember_org(self.settings, org, str(folder))
            settings.save(self.settings)
            self._reload_org_menu()
            self.note = f"Added {org}"
            self.switch_org(org)

        self.run_task(work, "Vault copied to this computer", on_success=cloned, refresh=False,
                      label="Cloning the vault (this can take a while)")

    def _org_setup(self, org):
        """Edit an org: its code, vault folder and starting part number."""
        folder = org_menu.known_orgs(self.settings).get(org, "") if org else ""
        start, base_digits, variant_digits = 1, part_number.DEFAULT_BASE_DIGITS, part_number.DEFAULT_VARIANT_DIGITS
        if folder and Path(folder).is_dir():
            try:
                start = config.get_start_number(folder)
                base_digits, variant_digits = config.get_digits(folder)
            except config.ConfigError:
                pass
        result = org_dialog.OrgDialog(self, org or "", folder, start, base_digits, variant_digits,
                           title=f"Org setup - {org}" if org else "Org setup").show()
        if not result:
            return
        new_org, new_folder, new_start, new_base_digits, new_variant_digits = result
        try:
            config_write.save(new_folder, org=new_org, start_number=new_start,
                        base_digits=new_base_digits, variant_digits=new_variant_digits)
        except (config.ConfigError, OSError) as e:
            messagebox.showerror("Org setup", f"Could not save the settings in the vault:\n\n{e}", parent=self)
            return
        if org and org != new_org:
            orgs = org_menu.known_orgs(self.settings)
            orgs.pop(org, None)
            self.settings["orgs"] = orgs
        org_menu.remember_org(self.settings, new_org, new_folder)
        settings.save(self.settings)
        self.note = ("Saved. Commit and push .litterbox/config.yaml so your team gets the same org setup")
        self.switch_org(new_org)

    def create_vault(self):
        """Create new vault...: turn an empty cloned repository into a vault (see init_vault.py)."""
        if not messagebox.askyesno("Create new vault", org_menu.CREATE_VAULT_INTRO, parent=self):
            return
        result = org_dialog.OrgDialog(self, "", "", 1, part_number.NEW_VAULT_BASE_DIGITS, part_number.DEFAULT_VARIANT_DIGITS,
                           title="Create new vault", save_text="Create").show()
        if not result:
            return
        org, folder, start, base_digits, variant_digits = result
        checked = create_vault.plan(folder, org, start, base_digits, variant_digits)
        if not checked.ok:
            messagebox.showerror("Create new vault", "\n\n".join(checked.problems), parent=self)
            return
        if checked.warnings and not messagebox.askyesno(
                "Create new vault", "\n\n".join(checked.warnings) + "\n\nCreate the vault anyway?", parent=self):
            return

        def made(created):
            org_menu.remember_org(self.settings, created.org, folder)
            settings.save(self.settings)
            self._reload_org_menu()
            self.switch_org(created.org)
            messagebox.showinfo("Create new vault", org_menu.vault_created_text(created), parent=self)

        self.run_task(lambda: create_vault.create(folder, org, start, base_digits, variant_digits),
                      f"Created the {checked.org} vault", on_success=made, refresh=False)

    def _say(self, text, tone="normal"):
        color = {"normal": theme.MUTED, "warn": theme.WARN, "error": theme.ERROR}[tone]
        self.status.configure(text=text, text_color=color)
        for window in self._team_windows():
            window.say(text, tone)

    def _popup_parent(self):
        """Where a pop-up should open. From a Team or My Tasks window it opens over that window, so closing it
        doesn't leave the main window in front."""
        try:
            focused = self.focus_get()
            top = focused.winfo_toplevel() if focused is not None else self
        except Exception:
            return self
        return top if isinstance(top, (team_window.TeamWindow, tasks_window.TasksWindow, workflows_dialog.WorkflowsDialog, request_dialog.WorkflowRequestDialog, reassign_dialog.ReassignDialog, roles_dialog.RolesDialog,
                            person_dialog.PersonDialog)) else self

    def _team_windows(self):
        return [w for w in self.winfo_children() if isinstance(w, team_window.TeamWindow) and w.winfo_exists()]

    def _log(self, text):
        settings.append_log(text)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _watch_for_freezes(self, last=None):
        """Every quarter second; if the window was too busy to run this on time, say so in the log."""
        now = time.monotonic()
        if last is not None and now - last > 1.5:
            release_button.click_log(f"the window was frozen for {now - last:.1f}s")
        self.after(250, lambda: self._watch_for_freezes(now))

    @property
    def busy(self):
        """True while any job is queued, running or about to be shown. The window still works; only things that
        must not overlap with a running job (switching org, the Import window) check this."""
        return self.jobs.active()

    def _sync_busy(self):
        """Bring the banner, the buttons and the 'busy' marks in the list up to date with the job queue."""
        busy = self.busy
        if busy != self._was_busy:
            release_button.click_log(f"busy={busy}")
            self._was_busy = busy
            self.org_menu.configure(state="disabled" if busy else "normal")      # not while jobs run on this vault
            for window in self._team_windows():
                window.set_busy(busy)
        self._update_banner()
        if self.jobs.pending_parts() != self._shown_pending:
            self._render()                                                        # also updates the buttons
        else:
            self._update_buttons()

    def _update_banner(self):
        state = self.jobs.banner()
        color = {jobs.READY: theme.GREEN, jobs.WORKING: theme.BANNER_YELLOW, jobs.ERROR: theme.RED}[state.kind]
        text_color = "#1b1b1b" if state.kind == jobs.WORKING else "white"
        self.banner.configure(fg_color=color)
        self.banner_title.configure(text=state.title, text_color=text_color)
        self.banner_detail.configure(text=state.detail, text_color=text_color)
        if state.kind == jobs.ERROR:
            self.banner_details_button.grid(row=0, column=1, padx=(4, 4), pady=(8, 0))
            self.banner_dismiss_button.grid(row=0, column=2, padx=(0, 10), pady=(8, 0))
        else:
            self.banner_details_button.grid_remove()
            self.banner_dismiss_button.grid_remove()

    def show_errors(self):
        notes = self.jobs.errors()
        if notes:
            error_details.ErrorDetailsWindow(self, error_text.error_report_text(notes), self.dismiss_errors)

    def dismiss_errors(self):
        self.jobs.dismiss_errors()
        self._update_banner()
        self._say("Ready")

    def _on_close(self):
        """Closing while jobs are still running could leave half-finished work, so ask first."""
        if self.busy and not messagebox.askyesno(
                "Litterbox is still working",
                "Litterbox is still working in the background. Closing now can leave a check-in half done "
                "(your locks stay, and you can run it again next time).\n\nClose anyway?", parent=self):
            return
        self.destroy()

    def _ask(self, text, title):
        """Ask for one line of text. Returns None if the user cancels."""
        return text_input.InputDialog(text=text, title=title).get_input()

    def _update_buttons(self):
        """Grey out the buttons that can't be used on the current selection: a button is lit only if every part it
        would act on is one it can be used on, and has no job in progress."""
        if not getattr(self, "action_buttons", None):
            return
        tree = self.tree
        highlighted = [parse_pn(iid) for iid in tree.selection()]
        states = action_rules.button_states(self._ticked_pns(), highlighted, self.rows_by_pn, self.jobs.pending_parts())
        for text, button in self.action_buttons.items():
            button.configure(state="normal" if states.get(text) else "disabled")
        deselect = getattr(self, "deselect_button", None)
        if deselect is not None:
            deselect.configure(state="normal" if self.ticked or highlighted else "disabled")

    def _deselect_all(self):
        """Clear every box (and the highlight)."""
        self._set_ticks(list(self.tree.get_children()) + list(self.ticked), False)
        self.tree.selection_set(*[])
        self._update_buttons()

    def _ticked_pns(self):
        """The ticked parts that are shown in the list right now (a tick on a filtered-out part is ignored)."""
        ticked = getattr(self, "ticked", set())
        return [parse_pn(iid) for iid in self.tree.get_children() if iid in ticked]

    def _selected_pns(self, action=None):
        """The parts an action applies to: see action_rules.choose_targets."""
        highlighted = [parse_pn(iid) for iid in self.tree.selection()]
        if action is None:
            return highlighted
        return action_rules.choose_targets(action, self._ticked_pns(), highlighted)

    def _on_tree_click(self, event):
        """A click in the tick column flips that row's box and leaves the highlight alone."""
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            shown = list(self.tree.get_children())
            anchor = getattr(self, "last_tick", None)
            if list_view.shift_held(event) and anchor in shown:   # Shift: tick everything from the last click to here
                self._set_ticks(list_view.range_between(shown, anchor, iid), anchor in self.ticked)
            else:
                self._set_ticks([iid], iid not in self.ticked)
            self.last_tick = iid
        return "break"

    def _tick_highlighted(self, event=None):
        chosen = list(self.tree.selection())
        if chosen:
            self._set_ticks(chosen, not all(iid in self.ticked for iid in chosen))
        return "break"

    def _toggle_all_ticks(self):
        shown = list(self.tree.get_children())
        self._set_ticks(shown, not (shown and all(iid in self.ticked for iid in shown)))

    def _set_ticks(self, iids, on):
        for iid in iids:
            (self.ticked.add if on else self.ticked.discard)(iid)
            if not self.tree.exists(iid):
                continue
            self.tree.set(iid, "tick", list_view.TICK_ON if on else list_view.TICK_OFF)
            kinds = [t for t in self.tree.item(iid, "tags") if t != "ticked"]
            self.tree.item(iid, tags=list_view.row_tags(kinds[0], on) if kinds else ())
        shown = self.tree.get_children()
        self.tree.heading("tick", text=list_view.TICK_ON if shown and all(i in self.ticked for i in shown) else list_view.TICK_OFF)
        self._say(list_view.tick_text(len(self._ticked_pns())))
        self._update_buttons()

    def _plan(self, action):
        """Work out what the selected parts allow. Shows the reason and returns None if nothing can be done."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
            return None
        plan = action_rules.plan_action(action, self._selected_pns(action), self.rows_by_pn, self.jobs.pending_parts())
        if plan.message:
            self._say(plan.message, "warn")
            return None
        return plan

    # ------------------------------------------------------------------
    # Running git work in the background so the window never freezes
    # ------------------------------------------------------------------
    def run_task(self, work, done_text, on_success=None, refresh=True, is_refresh=False, label="Working",
                 parts=(), kind="task"):
        """Queue work() to run in the background, after anything already queued. Then show done_text, call
        on_success(result) and refresh the list. `label` is what the banner says while it runs; `parts` are the
        parts it changes, which are marked busy until it is done."""
        ahead = self.jobs.active()
        job = jobs.Job(label=label, work=work, parts=tuple(str(p) for p in parts), kind=kind,
                       token=(done_text, on_success, refresh, is_refresh))
        if not ahead and settings.DEBUG:
            self._working_since = time.monotonic()
            self.after(1000, self._show_elapsed)
        self.jobs.submit(job)
        self._say(f"Queued: {label.lower()}" if ahead else f"{label}...")
        self._sync_busy()
        return True

    def _show_elapsed(self):
        """While a task runs, show how long it has taken, so a slow host looks slow rather than stuck."""
        if not self.jobs.working():
            return
        seconds = int(time.monotonic() - self._working_since)
        if seconds >= 3:
            self._say(f"Working... {seconds}s (the host may be slow)", "warn" if seconds >= 20 else "normal")
        self.after(1000, self._show_elapsed)

    def _poll_queue(self):
        try:
            self._drain_queue()
        finally:
            self.after(100, self._poll_queue)

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "update":
                    self._offer_update(payload)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass

    def _finish(self, outcome):
        """A job has finished: show how it went, run its follow-up, and free its parts."""
        job = outcome.job
        done_text, on_success, refresh, is_refresh = job.token
        try:
            self._show_outcome(job, outcome.result, outcome.error, done_text, on_success, refresh, is_refresh)
        except Exception as e:                      # a bug in a handler must not kill the window
            self._log(f"INTERNAL ERROR: {e!r}")
            self.jobs.add_error(job.label, f"Something unexpected went wrong: {e!r}",
                                error_text.error_advice("unexpected error"))
        finally:
            self.jobs.finished(job)
            self._sync_busy()

    def _show_outcome(self, job, result, error, done_text, on_success, refresh, is_refresh):
        if isinstance(error, NothingToSaveError):
            self.note = ""
            self._say("Nothing to save: nothing was different.")
            messagebox.showinfo("Nothing to save", str(error), parent=self._popup_parent())
        elif error:
            # A real problem: no pop-up (you may be busy elsewhere). The banner turns red; Details says what to do.
            self.note = ""
            self._log("ERROR: " + error)
            self.jobs.add_error(job.label, error, error_text.error_advice(error))
            self._say("Something went wrong. Press Details... on the red banner.", "error")
        else:
            if not is_refresh:
                self.note = done_text
            self._say(done_text)
            if on_success:
                on_success(result)
        if refresh:
            self.refresh()

    # ------------------------------------------------------------------
    # The list
    # ------------------------------------------------------------------
    def refresh(self):
        repo = self.repo()
        def work():
            def find_out_who():
                try:
                    return team_identity.current(repo)
                except LitterboxError as e:           # a damaged team file must not hide the parts
                    return team_identity.Identity(team_identity.UNVERIFIED, detail=str(e).splitlines()[0])

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=2) as pool:      # the list and "who am I" don't depend on each other
                who_job = pool.submit(find_out_who)
                rows = part_status.get_status(repo)
                who = who_job.result()
            if diagnostics.DEBUG:
                diagnostics.LOG(f"Refreshed the list in {time.monotonic() - started:.1f}s")
            return rows, who

        def show(result):
            rows, who = result
            self.identity = who
            self._show_identity()
            self._show_rows(rows)

        self.run_task(work, "Up to date", on_success=show, refresh=False, is_refresh=True, label="Refreshing the list",
                      kind="refresh")

    def _show_rows(self, rows):
        self.rows = rows
        self.rows_by_pn = {row.pn: row for row in rows}
        self._refresh_tasks()
        shown = self._render()
        if self.pending_select:
            if self.tree.exists(self.pending_select):
                self.tree.selection_set(self.pending_select)
                self.tree.see(self.pending_select)
            self.pending_select = None
        if not rows:
            self._say("No parts found. Check that this is your vault folder (it should contain a PN-logs folder).", "warn")
            return
        count = f"{shown} of {len(rows)} parts shown" if shown != len(rows) else f"{len(rows)} parts"
        ticked = len(self._ticked_pns())
        count += f"   |   {ticked} ticked" if ticked else ""
        self._say((self.note + "   |   " if self.note else "") + count)

    def _render(self):
        """Redraw the list using the search box and filters. Returns how many rows are shown."""
        rows = list_view.filter_rows(self.rows, self.search.get(), self.view.get(), bool(self.void_box.get()))
        self.ticked &= {str(row.pn) for row in self.rows}                     # parts that no longer exist lose their tick
        if not self.void_box.get():                                           # so do void parts that are now hidden
            self.ticked -= {str(row.pn) for row in self.rows if row.kind == "void"}
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        busy = self.jobs.pending_parts()                                    # parts with a job queued or running
        self._shown_pending = dict(busy)
        for row in rows:
            mark = busy.get(str(row.pn))
            self.tree.insert("", "end", iid=str(row.pn),
                             tags=list_view.row_tags(row.kind, str(row.pn) in self.ticked) + (("busy",) if mark else ()),
                             values=(
                list_view.TICK_ON if str(row.pn) in self.ticked else list_view.TICK_OFF,
                row.pn.short, row.name, row.description, "Yes" if row.cots else "", row.revision,
                job_text.busy_state_text(row.state, mark) if mark else row.state,
                list_view.file_types(row.files)))
        keep = [str(row.pn) for row in rows if str(row.pn) in previous]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self._update_buttons()
        return len(rows)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def get_latest(self):
        repo = self.repo()
        self.run_task(lambda: get_latest.get_latest(repo), "Downloaded the latest changes", label="Getting the latest",
                      on_success=lambda changed: self._warn_open_files(changed))

    def new_part(self):
        """Open the New Part pop-up, then create the number in the background."""
        if not self._may("create"):
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (box next to the title).", "warn")
            return
        repo, org = self.repo(), self.org
        request = new_part_dialog.NewPartDialog(self, repo, org).show()
        if not request:
            return
        def work():
            pn = create.new_part(repo, request["name"], request["description"],
                                 base=request["base"], variant=request["variant"], org=org)
            try:
                checkout.checkout(repo, pn)            # a new part starts out checked out to its creator
            except LitterboxError as e:
                return pn, str(e)
            return pn, ""

        def created(result):
            pn, problem = result
            self.note = f"Created {pn}" + (f" (could not check it out: {problem})" if problem else " and checked it out to you")
            self.pending_select = str(pn)
            self.search.delete(0, "end")            # make sure the new row isn't filtered out
            filename_dialog.FilenameDialog(self, pn)

        self.run_task(work, "Created", on_success=created)

    def import_cots(self):
        """Open the Import COTS window: the same as Import, but every part is recorded as purchased."""
        self.import_cad(cots=True)

    def import_cad(self, cots=False):
        """Open the Import window (choose old CAD folders, review the table, Finish & Import)."""
        if not self._may("create"):
            return
        if self.busy:
            self._say("Import needs the vault to itself. Wait for the banner to turn green, then try again.", "warn")
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (box next to the title).", "warn")
            return

        def imported(result):
            self.note = f"Imported {len(result.pns)} {'COTS ' if cots else ''}part(s)"
            self.search.delete(0, "end")
            repo, pns = self.repo(), list(result.pns)
            if cots or not pns:
                self.refresh()
                return
            # Record which parts each imported assembly uses (a separate small step after the import)
            self.run_task(lambda: reference_rescan.rescan(repo, pns, log=lambda text: self.queue.put(("log", text))),
                          self.note)

        import_window.ImportWindow(self, self.repo(), self.org, imported, log=lambda text: self.queue.put(("log", text)), cots=cots)

    def _warn_open_files(self, paths):
        names = checkin_text.cad_changes(paths)
        if names:
            messagebox.showinfo(
                "Newer versions downloaded",
                "These files were updated:\n\n  " + "\n  ".join(names) +
                "\n\nIf any of them are open in SolidWorks, close and reopen them "
                "so you aren't looking at an old copy.")

    def _show_identity(self):
        text, tone = team_text.identity_banner(self.identity)
        self.identity_label.configure(text=text, text_color=theme.WARN if tone == "warn" else theme.MUTED)
        self._refresh_tasks()

    # ------------------------------------------------------------------
    # My Tasks and the release workflow (see workflow.py)
    # ------------------------------------------------------------------
    def _task_windows(self):
        return [w for w in self.winfo_children() if isinstance(w, tasks_window.TasksWindow) and w.winfo_exists()]

    def _refresh_tasks(self):
        """Update the My Tasks button's count and any open My Tasks window."""
        button = getattr(self, "tasks_button", None)
        if button is None:
            return
        tasks = workflow_tasks.tasks_from_rows(self.rows, self.identity)
        button.configure(text=task_text.tasks_button_text(workflow_tasks.count_for_me(tasks)))
        for window in self._task_windows():
            window.reload()

    def show_tasks(self):
        windows = self._task_windows()
        if windows:
            windows[0].reload()
            windows[0].lift()
            return
        tasks_window.TasksWindow(self)

    def task_sign(self, task):
        comment = self._ask("Comment (optional):", f"Approve: {task.label}")
        if comment is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_signoff.sign_off(repo, pns, comment), f"Signed off {task.label}",
                      on_success=lambda result: self._signed(task, result))

    def _signed(self, task, result):
        text, _warn = task_text.signoff_result_text(result)
        if text:
            messagebox.showwarning("Sign-off saved", text)
        elif result.completed:
            self.note = f"Signed off; {workflow_templates.label_of(task.action)} done on {len(result.completed)} part" \
                        f"{'s' if len(result.completed) != 1 else ''}"

    def task_reject(self, task):
        reason = self._ask_reason("Why are you rejecting it? The person who asked will see this.",
                                  f"Reject: {task.label}")
        if reason is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_responses.reject(repo, pns, reason), f"Rejected {task.label}")

    def task_complete(self, task):
        repo, pns = self.repo(), task.pns
        label = workflow_templates.label_of(task.action)
        if messagebox.askokcancel(f"{label} {task.label}", f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow_signoff.complete_many(repo, pns), f"{label} done: {task.label}")

    def task_withdraw(self, task):
        repo, pns = self.repo(), task.pns
        if messagebox.askyesno(f"Withdraw {task.label}", "Withdraw this request? The sign-offs so far are "
                                                         "discarded, and you can ask again later."):
            self.run_task(lambda: workflow_responses.withdraw(repo, pns), f"Withdrew the request for {task.label}")

    def task_override(self, task):
        label = workflow_templates.label_of(task.action)
        reason = self._ask_reason(f"Why {label.lower()} without the sign-offs? This is recorded permanently.",
                                  f"Admin override: {label.lower()} {task.label}")
        if reason is None:
            return
        repo, pns, action = self.repo(), task.pns, task.action
        if messagebox.askokcancel(f"{label} {task.label}", f"{label} without the required sign-offs?\n\nReason: "
                                                           f"{reason}\n\nThis is recorded as an Admin override."):
            self.run_task(lambda: workflow_signoff.override(repo, pns, reason, action=action),
                          f"{label} done: {task.label} (Admin override)")

    def task_reassign(self, task):
        directory = self.identity.directory
        if directory is None:
            return
        chosen = reassign_dialog.ReassignDialog(self, task, directory).show()
        if chosen is None:
            return
        slot, person_id = chosen
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_responses.reassign(repo, pns, slot, person_id), f"Changed who signs {task.label}")

    # -- starting a workflow ------------------------------------------------
    def _one_part_only(self, action, plan):
        """Without a workflow these actions work on one part at a time. True if that's what was chosen."""
        if len(plan.targets) == 1:
            return True
        self._say(f"Select just one part to {action_rules.NAME[action]}. (This vault has no workflow for it, so it happens "
                  "directly, one part at a time.)", "warn")
        return False

    def _workflow_start(self, action, plan):
        """If this vault has workflows for the action, deal with it here (open the Workflow window, or finish a
        request that has all its sign-offs) and return True. Return False when it should just happen."""
        repo = self.repo()
        try:
            templates = workflow_store.templates_for(repo, action)
        except LitterboxError as e:
            messagebox.showerror("Litterbox", error_text.shorten(str(e)))
            return True
        pending = [pn for pn in plan.targets if self.rows_by_pn[pn].kind == "pending"]
        if not templates and not pending:
            return False
        if pending:
            if len(pending) != len(plan.targets):
                self._say("Some of these already have a request waiting. Select them separately.", "warn")
            else:
                self._finish_pending(action, pending)
            return True
        directory, me = self.identity.directory, self.identity.person
        if directory is None or me is None:
            self._say("Set up the team first (Team... > Set Up Team): sign-offs are done by people on it.", "warn")
            return True
        parts = [(pn, self.rows_by_pn[pn].name) for pn in plan.targets]
        chosen = request_dialog.WorkflowRequestDialog(self, action, parts, templates, directory, me.id).show()
        if not chosen:
            return True
        pns, label = list(plan.targets), workflow_templates.label_of(action)
        self.run_task(lambda: workflow_request.request(repo, pns, action, chosen["template"], chosen["assignments"],
                                               chosen["extras"], chosen["reason"]),
                      f"Started the {label} workflow on {len(pns)} part{'s' if len(pns) != 1 else ''}")
        return True

    def _finish_pending(self, action, pns):
        """The action's button on parts that already have a request: finish it if everyone has signed, else say
        what is missing."""
        repo, label = self.repo(), workflow_templates.label_of(action)
        rows = [self.rows_by_pn[pn] for pn in pns]
        other = next((r for r in rows if r.pending.get("action") != action), None)
        if other is not None:
            messagebox.showinfo(label, f"{other.pn} has a {workflow_templates.label_of(other.pending.get('action'))} request "
                                       "waiting for sign-offs. Open My Tasks to approve, reject or withdraw it.")
            return
        waiting = next((r for r in rows if not signoff_slots.is_complete(r.pending)), None)
        if waiting is not None:
            messagebox.showinfo(label, f"{waiting.pn} is still waiting for: " + ", ".join(
                signoff_slots.waiting_on(waiting.pending)) + ".\n\nOpen My Tasks to approve, reject or withdraw the "
                                                        "request.")
            return
        if messagebox.askokcancel(f"{label} {len(pns)} part{'s' if len(pns) != 1 else ''}",
                                  f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow_signoff.complete_many(repo, pns), f"{label} done: {', '.join(map(str, pns))}")

    def _may(self, action):
        """True if you may do `action`; otherwise says why in the status line."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
        return allowed

    def show_team(self):
        release_button.click_log("opening the Team window")
        team_window.TeamWindow(self)
        release_button.click_log("the Team window is built")

    def who_am_i(self):
        repo = self.repo()
        parent = self._popup_parent()                   # the Team window if that's where you pressed it

        def show(who):
            self.identity = who
            self._show_identity()
            messagebox.showinfo("Who am I?", team_text.who_am_i_text(who) if who.state != team_identity.UNVERIFIED
                                else who.message(), parent=parent)

        self.run_task(lambda: team_identity.current(repo, refresh=True), "Checked who you are", on_success=show,
                      refresh=False)

    def set_up_team(self):
        if not messagebox.askokcancel(
                "Set up the team",
                "This creates the team list for this vault and makes YOU its Owner.\n\nFrom then on, only people an "
                "Admin adds to the list can change anything; everyone else can look and open files.\n\n"
                "Litterbox needs the internet to ask the host who you are."):
            return
        repo = self.repo()
        self.run_task(lambda: (team_setup.setup_team(repo), team_identity.current(repo, refresh=True))[1], "The team is set up",
                      on_success=self._team_changed)

    def _team_changed(self, who):
        self.identity = who
        self._show_identity()
        for child in self.winfo_children():
            if isinstance(child, team_window.TeamWindow) and child.winfo_exists():
                child.reload()

    def _stage(self, window, label, change, needs_owner=False):
        """Add a change to the Team window's unsaved changes. Returns "" if it was taken, else why not."""
        draft = window.draft
        if draft is None:
            return "The team isn't set up yet."
        try:
            draft.stage_people(label, change, needs_owner)
        except LitterboxError as e:
            return error_text.shorten(str(e))
        window.reload()
        return ""

    def edit_person(self, window, person_id, adding=False):
        if not self._may("manage_people"):
            return
        directory = window.draft.directory if window.draft is not None else self.identity.directory
        person = None if adding else (directory.get(person_id) if person_id else None)
        if person is None and not adding:
            self._say("Select a person first.", "warn")
            return

        def apply(fields):
            if person is None:
                new_id = fields.pop("id")
                return self._stage(window, f"Add {fields['name']}",
                                   lambda d, who: team_editing.add_person(d, who, new_id, **fields))
            if team_text.person_unchanged(person, fields):
                return ""
            pid = person.id
            return self._stage(window, f"Edit {person.name}", lambda d, who: team_editing.update_person(d, who, pid, **fields))

        person_dialog.PersonDialog(window, person, directory.roles, [p.id for p in directory.people],
                     self.identity.access == team_model.OWNER, apply=apply).show()

    def toggle_person(self, window, person_id):
        if not self._may("manage_people"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select a person first.", "warn")
            return
        turn_on, pid = not person.active, person.id
        problem = self._stage(window, f"Switch {'on' if turn_on else 'off'} {person.name}",
                              lambda d, who: team_editing.set_active(d, who, pid, turn_on))
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_roles(self, window):
        if not self._may("manage_people") or window.draft is None:
            return
        directory = window.draft.directory
        roles_dialog.RolesDialog(window, directory.roles, lambda role: team_editing.holders_of(window.draft.directory, role),
                    apply=lambda roles: self._stage(window, "Roles", lambda d, who: team_editing.set_roles(
                        d, who, roles, scrub=True))).show()

    def transfer_owner(self, window, person_id):
        if not self._may("transfer_owner"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select the person who will become the Owner.", "warn")
            return
        if not messagebox.askokcancel(
                "Transfer ownership",
                f"Make {person.name} the Owner? You will become an Admin, and only {person.name} will be able to "
                "hand ownership on again.\n\nThis takes effect when you press Save.", parent=window):
            return
        pid = person.id
        problem = self._stage(window, f"{person.name} becomes the Owner",
                              lambda d, who: team_editing.transfer_owner(d, who, pid), needs_owner=True)
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_vault_settings(self, window):
        if not self._may("manage_settings"):
            return
        repo = self.repo()
        try:
            current = {"commit_style": config.get_commit_style(repo), "release_rule": config.get_release_rule(repo),
                       "require_signatures": config.get_require_signatures(repo)}
        except config.ConfigError as e:
            messagebox.showwarning("Vault settings", f"The settings file has a problem:\n\n{e}", parent=window)
            return
        chosen = vault_settings_dialog.VaultSettingsDialog(window, current).show()
        changes = team_text.changed_settings(current, chosen)
        if not changes:
            return
        if changes.get("require_signatures") and not messagebox.askokcancel(
                "Require signed commits",
                "From now on, Litterbox refuses to upload any commit that is not signed by a key on the team list. "
                "Anyone who has not set up signing (Team > Signing...) will not be able to upload until they do."
                "\n\nTurn this on?", parent=window):
            return
        self.run_task(lambda: vault_settings.edit(repo, **changes), "Vault settings saved")

    def edit_workflow(self, window):
        if not self._may("manage_workflows") or window.draft is None:
            return
        draft = window.draft
        if not draft.directory.roles:
            messagebox.showinfo("Workflows", "This org has no roles yet. Add some in Team... > Roles first.",
                                parent=window)
            return

        def apply(ops, editor):
            wanted = editor.templates()
            notes = []
            for op in ops:
                if op["op"] == "set":
                    template = wanted[op["action"]][op["name"]]
                    notes += [f"{workflow_templates.label_of(op['action'])} {op['name']}: {n}"
                              for n in workflow_editing.role_warnings(template, draft.directory)]
            if notes and not messagebox.askyesno(
                    "Workflows", "\n".join(notes) + "\n\nUntil that is fixed a request will wait for an Admin "
                    "override. Keep this change anyway?", parent=window):
                return "Change the roles or the workflow, or press Cancel."

            def change(templates, _directory):
                workflow_editing.apply_ops(templates, ops)

            try:
                draft.stage_workflow(workflow_editor.ops_label(ops), change)
            except LitterboxError as e:
                return error_text.shorten(str(e))
            window.reload()
            return ""

        workflows_dialog.WorkflowsDialog(window, draft.directory.roles, draft.templates, apply=apply).show()

    def save_team(self, window):
        """The Team window's Save: upload every staged change in one go."""
        draft = window.draft
        if draft is None or not draft.dirty:
            return
        repo = self.repo()

        def work():
            draft.save(repo)
            return team_identity.current(repo, probe=False)

        self.run_task(work, "Saved the team changes", on_success=self._team_changed, refresh=False)

    def _run_batch(self, action, plan, func):
        """Run an engine call for every planned part together: func(repo, parts) -> (done, failed), which does
        one download and one upload for the lot."""
        repo, targets = self.repo(), list(plan.targets)
        self.run_task(
            lambda: func(repo, targets),
            "", on_success=lambda result: self._after_batch(action, plan, result),
            label=job_text.job_label(action, len(targets)), parts=targets)

    def _after_batch(self, action, plan, result):
        done, failed = result
        self.note = action_rules.summary(action, len(done), len(failed), len(plan.skipped))
        self._say(self.note, "warn" if failed else "normal")
        if failed:
            messagebox.showerror("Litterbox", error_text.shorten(
                "\n\n".join(f"{pn}: {message}" for pn, message in failed)))

        if action == "checkout":
            self._warn_open_files([path for _pn, r in done for path in r.changed_upstream])
        elif action in ("checkin", "save"):
            nothing = [str(pn) for pn, r in done if not r.uploaded]
            if nothing:
                messagebox.showinfo("Nothing to upload", "There were no changes to save in: " + ", ".join(nothing))
        elif action == "undo":
            left = [name for _pn, names in done for name in names]
            if left:
                messagebox.showinfo(
                    "New files kept",
                    "These new files were never uploaded, so they were left in your cad folder:\n\n  " +
                    "\n  ".join(left))

    def check_out(self):
        plan = self._plan("checkout")
        if plan:
            self._run_batch("checkout", plan, checkout.checkout_many)

    def _ask_comment_and_check_in(self, action, plan, allow_unchanged=frozenset()):
        """Ask for a comment, then check in (or save progress on) the planned parts."""
        keep_lock = action == "save"
        comment = self._ask("Describe your changes:\n\n" + checkin_text.CHECKIN_CAUTION,
                            "Save Progress" if keep_lock else "Check In")
        if comment is None:                                  # cancelled
            return
        comment = comment.strip() or "Update"
        reader = reference_reader.make_reader(log=lambda text: self.queue.put(("log", text)))
        snapshot = self._watch_files(plan.targets)
        self._run_batch(action, plan, lambda repo, pns: checkin.checkin_many(
            repo, pns, comment, keep_lock=keep_lock, allow_unchanged=allow_unchanged, references_reader=reader,
            snapshot=snapshot))

    def _watch_files(self, targets):
        """Remember the files' sizes and times now, so a part saved after this click is not uploaded half way
        (see file_snapshot.py). Never stops the check-in: if it can't be done, there is just no protection."""
        try:
            return checkin.watch_files(self.repo(), {pn: self.rows_by_pn[pn].revision for pn in targets})
        except Exception as e:
            self._log(f"Could not watch the files for changes: {e!r}")
            return None

    def _check_in(self, keep_lock):
        action = "save" if keep_lock else "checkin"
        plan = self._plan(action)
        if not plan:
            return
        if keep_lock:                       # saving progress with no changes just does nothing
            self._ask_comment_and_check_in(action, plan)
            return
        # Check In: first look for parts with nothing to upload, and ask before going ahead.
        repo = self.repo()
        self.run_task(
            lambda: part_changes.change_reports(repo, plan.targets), "",
            on_success=lambda reports: self._confirm_unchanged(plan, reports),
            refresh=False, is_refresh=True)

    def _confirm_unchanged(self, plan, reports):
        unchanged = checkin_text.parts_without_changes(reports)
        if unchanged:
            dialog = confirm_dialogs.ConfirmDialog(
                self, "No changes detected", "No changes were detected in these files:",
                checkin_text.unchanged_lines(unchanged),
                note="Continue will still check the part in: the check-in is recorded in its log, "
                     "uploaded, and your lock is released. Cancel leaves everything as it is.",
                confirm_text="Continue")
            if not dialog.show():
                self._say("Check-in cancelled. Nothing was changed.", "warn")
                return
        self._ask_comment_and_check_in("checkin", plan, frozenset(pn for pn, _files in unchanged))

    def check_in(self):
        self._check_in(keep_lock=False)

    def save_progress(self):
        self._check_in(keep_lock=True)

    def undo_checkout(self):
        plan = self._plan("undo")
        if not plan:
            return
        if not messagebox.askyesno("Undo checkout", checkin_text.undo_prompt(plan.targets)):
            return
        self._run_batch("undo", plan, undoing.undo_checkout_many)

    def release(self):
        plan = self._plan("release")
        if not plan:
            return
        if self._workflow_start("release", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        # Step 1: find out exactly what would be released. Step 2: ask. Step 3: do it.
        self.run_task(lambda: planning.release_plans(repo, pns), "Checked what a release would include",
                      on_success=lambda plans: self._confirm_release(repo, plans), refresh=False)

    def _confirm_release(self, repo, plans):
        good, bad = [p for p in plans if p.ok], [p for p in plans if not p.ok]
        if not good:
            messagebox.showwarning("Can't release yet", confirmations.plans_problem_text(bad, "released"))
            return
        if len(plans) == 1:
            title, text = f"Release {good[0].pn}", confirmations.release_confirm_text(good[0])
        else:
            title, text = f"Release {len(good)} parts", confirmations.release_many_confirm_text(good, bad)
        if not messagebox.askokcancel(title, text):
            return
        pns = [p.pn for p in good]
        skipped = [(p.pn, p.problems[0]) for p in bad]
        self.run_task(lambda: lifecycle.release_many(repo, pns), "",
                      on_success=lambda result: self._after_batch("release", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("release", len(pns)), parts=pns)

    def open_part(self, drawing=False):
        """Open the part's model, or (drawing=True) its drawing, in the program for that file type.

        If the part has both a released and a working revision, ask which one."""
        plan = self._plan("open_drawing" if drawing else "open")
        if not plan:
            return
        pn = plan.targets[0]
        row = self.rows_by_pn[pn]
        waiting = self.jobs.pending_parts().get(str(pn))
        if waiting and not messagebox.askokcancel(
                "Still being uploaded", checkin_text.open_while_busy_text(pn, waiting), parent=self):
            return
        problem = opening_text.open_message(row, drawing)
        if problem:
            self._say(problem, "warn")
            return
        choices = opening_text.open_choices(row, drawing)
        if len(choices) == 1:
            rev = choices[0][0]
        else:
            rev = revision_picker.RevisionPickerDialog(self, pn, [(history_text.revision_label(row, r), r) for r, _f in choices],
                                       "Open drawing of" if drawing else "Open").show()
            if rev is None:
                return
        if not drawing and self._offer_reference_review(pn, row, rev):
            return
        self._open_revision(pn, rev, drawing)

    def _offer_reference_review(self, pn, row, rev):
        """An assembly in work that uses out-of-date parts: offer to review them first. True if the review opened."""
        if row.kind not in ("ok", "mine", "unclaimed") or rev != row.revision:
            return False
        try:
            stale = [u for u in reference_queries.uses(self.repo(), pn, rev) if u.replaceable]
        except LitterboxError:
            return False
        if not stale:
            return False
        if messagebox.askyesno("Parts out of date", reference_text.stale_open_text(pn, stale)):
            self._load_references(pn)
            return True
        return False

    def show_references(self):
        plan = self._plan("references")
        if plan:
            self._load_references(plan.targets[0])

    def _load_references(self, pn, window=None):
        """Open the References window for a part (or, with `window`, refresh the one that is already open)."""
        repo = self.repo()

        def load():
            records = reference_model.load_records(repo)
            outdated = reference_queries.outdated_parts(repo, records)
            return (records[pn].name if pn in records else "", reference_queries.uses(repo, pn, None, records),
                    reference_queries.where_used(repo, pn, records), pn in outdated, [p for p in outdated if p != pn])

        def show(r):
            if window is not None and window.winfo_exists():
                window.show(r[0], r[1], r[2], r[3], r[4])
            else:
                references_window.ReferencesWindow(self, pn, r[0], r[1], r[2], self._replace_references,
                                 this_outdated=r[3], others_outdated=r[4],
                                 on_update=lambda win, pns: self._update_references(pn, pns, win))

        self.run_task(load, "", refresh=False, is_refresh=True, on_success=show)

    def _update_references(self, pn, pns, window):
        """Read the assemblies' files (starting SolidWorks if it is not running) and store what they use.
        The References window stays open and is refreshed when this finishes."""
        repo = self.repo()

        def work():
            try:
                results = reference_rescan.rescan(repo, pns, log=lambda text: self.queue.put(("log", text)))
                return results, part_status.get_status(repo), ""
            except Exception as e:                       # the window must be given back either way
                return None, None, str(e)

        def done(result):
            results, rows, error = result
            if error:
                if window.winfo_exists():
                    window.set_idle()
                messagebox.showerror("Update references", error_text.shorten(error))
                return
            self._show_rows(rows)
            text, problems = reference_text.update_summary(results)
            if problems:
                messagebox.showwarning("Update references", text)
            self._load_references(pn, window)

        if not self.run_task(work, "Updated the lists of parts used", on_success=done, refresh=False):
            window.set_idle()

    def _replace_references(self, items):
        repo = self.repo()
        count = len({item.parent for item in items})
        if not messagebox.askokcancel(
                "Replace references",
                f"Point {count} assembl{'y' if count == 1 else 'ies'} at the latest released revision of the "
                "parts you ticked?\n\nAssemblies nobody has checked out are checked out, changed and checked "
                "back in. An assembly you already have checked out is changed in your copy and left for you to "
                "check in. Assemblies checked out by someone else are skipped."):
            return

        def done(results):
            text, problems = reference_text.replace_summary(results)
            (messagebox.showwarning if problems else messagebox.showinfo)("Replace references", text)

        self.run_task(lambda: reference_replace.replace_references(
            repo, items, log=lambda text: self.queue.put(("log", text))), "Updated references", on_success=done)

    def _open_revision(self, pn, rev, drawing=False):
        """Open one revision's model or drawing (used by the Open buttons and the History window)."""
        row = self.rows_by_pn.get(pn)
        files = history_text.row_revisions(row).get(rev, []) if row else []
        path = opener.pick_drawing(files) if drawing else opener.pick_model(files)
        if path is None:
            self._say(f"{pn.short} Rev {rev} has no {'drawing' if drawing else 'file'}.", "warn")
            return
        try:
            opener.open_path(Path(self.repo()) / path, self.settings.get("open_with"))
        except LitterboxError as e:
            messagebox.showwarning("Can't open", str(e))
            return
        self._say(f"Opening {PurePosixPath(path).name}...")

    def open_drawing(self):
        self.open_part(drawing=True)

    def edit_details(self):
        plan = self._plan("edit")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        row = self.rows_by_pn[pn]
        result = edit_details_dialog.EditDetailsDialog(self, pn, row.name, row.description).show()
        if result is None:
            self._say("Nothing was changed.")
            return
        name, description = result
        self.run_task(lambda: part_details.edit_details(repo, pn, name, description),
                      f"Updated the details of {pn}. Save Progress or Check In to upload them.")

    def revise(self):
        plan = self._plan("revise")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: revise.revise_plan(repo, pn), "Checked what a revision would create",
                      on_success=lambda revise_plan: self._confirm_revise(repo, revise_plan), refresh=False)

    def _confirm_revise(self, repo, revise_plan):
        pn = revise_plan.pn
        if not revise_plan.ok:
            messagebox.showwarning("Can't revise yet", confirmations.revise_problem_text(pn, revise_plan.problems))
            return
        reason = text_input.ReasonDialog(self, f"Revise {pn.short}", confirmations.revise_confirm_text(revise_plan),
                              "Why is it being revised? (a few words)", "Revise").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: revise.revise(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Rev {revise_plan.new_revision} of {pn.short} is checked out to you")

    def cancel_revision(self):
        plan = self._plan("cancel_revision")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: cancel_revision.cancel_revision_plan(repo, pn), "Checked what cancelling would do",
                      on_success=lambda cancel_plan: self._confirm_cancel_revision(repo, cancel_plan),
                      refresh=False)

    def _confirm_cancel_revision(self, repo, cancel_plan):
        pn = cancel_plan.pn
        if not cancel_plan.ok:
            messagebox.showwarning("Can't cancel", confirmations.cancel_problem_text(pn, cancel_plan.problems))
            return
        reason = text_input.ReasonDialog(self, f"Cancel Rev {cancel_plan.revision} of {pn.short}",
                              confirmations.cancel_confirm_text(cancel_plan),
                              "Why is it being cancelled? (a few words)", "Cancel revision").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: cancel_revision.cancel_revision(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Cancelled Rev {cancel_plan.revision} of {pn.short}")

    def make_cots(self):
        plan = self._plan("make_cots")
        if not plan:
            return
        if self._workflow_start("make_cots", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        self.run_task(lambda: planning.make_cots_plans(repo, pns), "Checked whether they can be made COTS",
                      on_success=lambda plans: self._confirm_make_cots(repo, plans), refresh=False)

    def _confirm_make_cots(self, repo, plans):
        good, bad = [p for p in plans if p.ok], [p for p in plans if not p.ok]
        if not good:
            messagebox.showwarning("Can't make COTS yet", confirmations.plans_problem_text(bad, "made COTS"))
            return
        if len(plans) == 1:
            title = f"Make {good[0].pn} COTS"
            text = confirmations.make_cots_confirm_text(good[0].pn, good[0].name, good[0].files)
        else:
            title, text = f"Make {len(good)} parts COTS", confirmations.make_cots_many_confirm_text(good, bad)
        if not messagebox.askokcancel(title, text):
            return
        pns = [p.pn for p in good]
        skipped = [(p.pn, p.problems[0]) for p in bad]
        self.run_task(lambda: lifecycle.make_cots_many(repo, pns), "",
                      on_success=lambda result: self._after_batch("make_cots", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("make_cots", len(pns)), parts=pns)

    def _ask_reason(self, text, title):
        """Ask for a reason. Returns None if cancelled or left blank (and says so)."""
        reason = self._ask(text, title)
        if reason is None:
            return None
        if not reason.strip():
            messagebox.showwarning(title, "A reason is required.")
            return None
        return reason.strip()

    def reopen(self):
        plan = self._plan("reopen")
        if not plan:
            return
        if self._workflow_start("reopen", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        cots = [pn for pn in pns if self.rows_by_pn[pn].kind == "cots"]
        if cots and not messagebox.askyesno("Unrelease COTS part" + ("s" if len(cots) > 1 else ""),
                                            confirmations.reopen_cots_warning(cots)):
            return
        what = str(pns[0]) if len(pns) == 1 else f"these {len(pns)} parts"
        reason = self._ask_reason(f"Why {'is' if len(pns) == 1 else 'are'} {what} being unreleased?", "Unrelease")
        if reason:
            self.run_task(lambda: lifecycle.reopen_many(repo, pns, reason), "",
                          on_success=lambda result: self._after_batch("reopen", plan, result),
                          label=job_text.job_label("reopen", len(pns)), parts=pns)

    def void(self):
        plan = self._plan("void")
        if not plan:
            return
        if self._workflow_start("void", plan):
            return
        repo = self.repo()
        pns, skipped = [], list(plan.skipped)
        for pn in plan.targets:
            problem = confirmations.void_problem(self.rows_by_pn[pn])
            if problem:
                skipped.append((pn, problem))
            else:
                pns.append(pn)
        if not pns:
            messagebox.showwarning("Can't void", "\n\n".join(why for _pn, why in skipped))
            return
        what = str(pns[0]) if len(pns) == 1 else f"these {len(pns)} parts"
        reason = self._ask_reason(f"Why {'is' if len(pns) == 1 else 'are'} {what} being voided?", "Void")
        if not reason:
            return
        if not messagebox.askyesno(
                "Void part" + ("s" if len(pns) != 1 else ""),
                f"Void {pns[0]}?\n\nIts number will never be used again, and it can't be checked out."
                if len(pns) == 1 else confirmations.void_many_confirm_text(pns)):
            return
        self.run_task(lambda: lifecycle.void_many(repo, pns, reason), "",
                      on_success=lambda result: self._after_batch("void", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("void", len(pns)), parts=pns)

    def show_history(self, event=None):
        if event is not None and self.tree.identify_column(event.x) == "#1":
            return                                              # double-clicking a tick box isn't asking for history
        chosen = self._selected_pns("open")                    # the highlighted row, or the one selected part
        if len(chosen) != 1:
            self._say("Click one part to see its history.", "warn")
            return
        try:
            record = record_store.load(self.repo(), chosen[0])
        except record_model.RegistryError as e:
            messagebox.showerror("Litterbox", str(e))
            return
        row = self.rows_by_pn.get(chosen[0])
        history_window.HistoryWindow(self, record, history_text.row_revisions(row) if row else {},
                      on_open=lambda rev, drawing, pn=chosen[0]: self._open_revision(pn, rev, drawing))
