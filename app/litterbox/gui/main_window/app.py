"""
app.py - the main Litterbox window (App).
"""

import queue
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from litterbox import diagnostics
from litterbox import version
from litterbox.gui import scaling
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import text_input
from litterbox.gui.dialogs.team import person_dialog
from litterbox.gui.dialogs.team import roles_dialog
from litterbox.gui.dialogs.workflow import reassign_dialog
from litterbox.gui.dialogs.workflow import request_dialog
from litterbox.gui.dialogs.workflow import review_dialog
from litterbox.gui.dialogs.workflow import superuser_sign_dialog
from litterbox.gui.dialogs.workflow import workflows_dialog
from litterbox.gui.logic import icon_files
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import org_menu
from litterbox.gui.logic import ui_scale
from litterbox.gui.main_window.actions.checkin_actions import CheckinActions
from litterbox.gui.main_window.actions.checkout_actions import CheckoutActions
from litterbox.gui.main_window.actions.create_actions import CreateActions
from litterbox.gui.main_window.actions.details_actions import DetailsActions
from litterbox.gui.main_window.actions.document_actions import DocumentActions
from litterbox.gui.main_window.actions.export_actions import ExportActions
from litterbox.gui.main_window.actions.generate_actions import GenerateActions
from litterbox.gui.main_window.actions.open_actions import OpenActions
from litterbox.gui.main_window.actions.reference_actions import ReferenceActions
from litterbox.gui.main_window.actions.release_actions import ReleaseActions
from litterbox.gui.main_window.actions.revise_actions import ReviseActions
from litterbox.gui.main_window.background_jobs import BackgroundJobs
from litterbox.gui.main_window.detail_pane import DetailPane
from litterbox.gui.main_window.file_rules import FileRules
from litterbox.gui.main_window.home_actions import HomeActions
from litterbox.gui.main_window.home_view import HomeView
from litterbox.gui.main_window.layout import WindowLayout
from litterbox.gui.main_window.menus import Menus
from litterbox.gui.main_window.org_switching import OrgSwitching
from litterbox.gui.main_window.parts_list import PartsList
from litterbox.gui.main_window.problem_reports import ProblemReports
from litterbox.gui.main_window.record_upgrading import RecordUpgrade
from litterbox.gui.main_window.sidebar import Sidebar
from litterbox.gui.main_window.solidworks_watch import SolidWorksWatch
from litterbox.gui.main_window.status_bar import StatusBar
from litterbox.gui.main_window.task_actions import TaskActions
from litterbox.gui.main_window.team_admin import TeamAdmin
from litterbox.gui.main_window.text_size import TextSize
from litterbox.gui.main_window.toolbox_setting import ToolboxSetting
from litterbox.gui.main_window.update_checks import UpdateChecks
from litterbox.gui.widgets import icon_images
from litterbox.gui.widgets import menu_bar
from litterbox.jobs import job_queue as jobs
from litterbox.team import team_identity
from litterbox.user import settings
from litterbox.vault import config


# Set to True to download the latest changes every time the app opens.
# (Off by default: a download can replace files that are open in SolidWorks.)
AUTO_GET_LATEST_ON_START = False


class App(WindowLayout, Menus, Sidebar, StatusBar, DetailPane, TextSize, UpdateChecks, OrgSwitching, BackgroundJobs,
          HomeView, HomeActions, PartsList, TaskActions, TeamAdmin, CreateActions, CheckoutActions, CheckinActions, ReleaseActions,
          ReviseActions, OpenActions, ReferenceActions, DetailsActions, ExportActions, GenerateActions, DocumentActions,
          SolidWorksWatch, FileRules, RecordUpgrade, ToolboxSetting, ProblemReports, ctk.CTk):
    """The main Litterbox window. Each area lives in its own file (the classes above); this file starts the window
    and holds the small helpers every area uses."""

    identity = team_identity.Identity(team_identity.LEGACY)       # replaced after the first refresh
    scale = 1.0                         # the display scaling times the Text size (see gui/scaling.py)
    screen = "parts"                    # what the sidebar is showing: parts, tasks, ecos or team
    sidebar_collapsed = False
    list_keys = tuple(c.key for c in list_columns.COLUMNS if c.shown)

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
        self.text_size = ui_scale.text_size(self.settings)
        scaling.set_text_size(self.text_size)
        self.geometry("1220x760")
        self.minsize(860, 540)
        self.scale = scaling.scale_of(self)
        self.icons = icon_images.IconImages(self, window_chrome.ASSETS_DIR, window_chrome.ICON_SETTING["choice"])

        self.queue = queue.Queue()      # messages from the background thread to the window
        # Every task runs here, one at a time, in the background (see job_queue.py). The window stays usable meanwhile.
        self.jobs = jobs.JobQueue(deliver=lambda outcome: self.queue.put(("done", outcome)))
        self._was_busy = False
        self._shown_pending = {}
        self.rows = []                  # every PartStatus from the engine
        self.identity = team_identity.Identity(team_identity.LEGACY)      # who you are on this vault's team (see people.py)
        self.rows_by_pn = {}
        self.action_buttons = {}        # button text -> button, for the ones that follow the selection
        self.ticked = set()             # the parts (as text) whose boxes are ticked
        self.list_keys = list_columns.shown_keys(self.settings.get("list_columns"))
        self.view = tk.StringVar(master=self, value="All")     # the parts list's view, chosen in the sidebar
        self.sidebar_choice = None      # True / False once the person has collapsed or opened the sidebar
        self.pending_select = None      # a part to select once the list reloads (the one just created)
        self.note = ""                  # what just happened, kept in the status line after a refresh

        # Everything the engine logs ("> git lfs lock ...") shows up in the log box.
        diagnostics.LOG = lambda message: self.queue.put(("log", message))

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda event: self.refresh())
        for number, name in enumerate(("parts", "tasks", "ecos", "team", "documents"), 1):
            self.bind(f"<Control-Key-{number}>", lambda event, name=name: self.show_screen(name))
        self._bind_text_size_keys()
        for title, key in menu_bar.ALT_KEYS.items():
            self.bind(f"<Alt-{key}>", lambda event, title=title: self.menu_bar.open_named(title))
        scaling.watch(self, self._rescale_soon)
        self.after(100, self._poll_queue)
        if settings.DEBUG:
            self._watch_for_freezes()

        if self.org and Path(self.repo()).is_dir():
            if AUTO_GET_LATEST_ON_START:
                self.get_latest()
            else:
                self.refresh()
        elif self.org:
            self._say(f"The vault folder for {self.org} wasn't found: {self.repo()}. Use File > Add org... to copy it to this computer again.", "warn")
        else:
            self._say("Choose File > Add org... to get started.", "warn")

        self._start_solidworks_watcher()
        self.after(120, self._reveal)
        self.after(4000, self._start_update_check)

    def _reveal(self):
        """Show the window now that the icon is set and everything is built."""
        self.deiconify()
        self.lift()

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------
    def repo(self):
        """The vault folder of the org that is open."""
        return org_menu.known_orgs(self.settings).get(self.org, "") if self.org else ""

    def _org_name(self):
        """The open org's full name from its vault settings, or its code."""
        try:
            return config.get_org_name(self.repo()) if self.repo() else ""
        except Exception:
            return self.org or ""

    def _popup_parent(self):
        """Where a pop-up should open. From a dialog that is open over the window (a workflow or a person, say) it
        opens over that dialog, so closing it doesn't leave the main window in front."""
        try:
            focused = self.focus_get()
            top = focused.winfo_toplevel() if focused is not None else self
        except Exception:
            return self
        return top if isinstance(top, (workflows_dialog.WorkflowsDialog, request_dialog.WorkflowRequestDialog,
                                       reassign_dialog.ReassignDialog, review_dialog.ReviewDialog,
                                       roles_dialog.RolesDialog, superuser_sign_dialog.SuperuserSignDialog,
                                       person_dialog.PersonDialog)) else self

    def _on_close(self):
        """Closing while jobs are still running could leave half-finished work, so ask first."""
        if self.busy and not messagebox.askyesno(
                "Litterbox is still working",
                "Litterbox is still working in the background. Closing now can leave a check-in half done "
                "(your locks stay, and you can run it again next time).\n\nClose anyway?", parent=self):
            return
        self._stop_solidworks_watcher()
        self.destroy()

    def _ask(self, text, title):
        """Ask for one line of text. Returns None if the user cancels."""
        return text_input.InputDialog(text=text, title=title).get_input()

    # -- starting a workflow ------------------------------------------------
    def _may(self, action):
        """True if you may do `action`; otherwise says why in the status line."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
        return allowed

    def _ask_reason(self, text, title):
        """Ask for a reason. Returns None if cancelled or left blank (and says so)."""
        reason = self._ask(text, title)
        if reason is None:
            return None
        if not reason.strip():
            messagebox.showwarning(title, "A reason is required.")
            return None
        return reason.strip()



