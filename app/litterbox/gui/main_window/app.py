"""
app.py - the main Litterbox window (App).
"""

import queue
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from litterbox import diagnostics
from litterbox import version
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import text_input
from litterbox.gui.dialogs.team import person_dialog
from litterbox.gui.dialogs.team import roles_dialog
from litterbox.gui.dialogs.workflow import reassign_dialog
from litterbox.gui.dialogs.workflow import request_dialog
from litterbox.gui.dialogs.workflow import workflows_dialog
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import icon_files
from litterbox.gui.logic import org_menu
from litterbox.gui.main_window.actions.checkin_actions import CheckinActions
from litterbox.gui.main_window.actions.checkout_actions import CheckoutActions
from litterbox.gui.main_window.actions.create_actions import CreateActions
from litterbox.gui.main_window.actions.details_actions import DetailsActions
from litterbox.gui.main_window.actions.open_actions import OpenActions
from litterbox.gui.main_window.actions.reference_actions import ReferenceActions
from litterbox.gui.main_window.actions.release_actions import ReleaseActions
from litterbox.gui.main_window.actions.revise_actions import ReviseActions
from litterbox.gui.main_window.background_jobs import BackgroundJobs
from litterbox.gui.main_window.layout import WindowLayout
from litterbox.gui.main_window.org_switching import OrgSwitching
from litterbox.gui.main_window.parts_list import PartsList
from litterbox.gui.main_window.task_actions import TaskActions
from litterbox.gui.main_window.team_admin import TeamAdmin
from litterbox.gui.main_window.update_checks import UpdateChecks
from litterbox.gui.windows import tasks_window
from litterbox.gui.windows import team_window
from litterbox.jobs import job_queue as jobs
from litterbox.team import team_identity
from litterbox.user import settings


# Set to True to download the latest changes every time the app opens.
# (Off by default: a download can replace files that are open in SolidWorks.)
AUTO_GET_LATEST_ON_START = False


class App(WindowLayout, UpdateChecks, OrgSwitching, BackgroundJobs, PartsList, TaskActions, TeamAdmin,
          CreateActions, CheckoutActions, CheckinActions, ReleaseActions, ReviseActions, OpenActions, ReferenceActions,
          DetailsActions, ctk.CTk):
    """The main Litterbox window. Each area lives in its own file (the classes above); this file starts the window
    and holds the small helpers every area uses."""

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

    def _log(self, text):
        settings.append_log(text)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

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

    # -- starting a workflow ------------------------------------------------
    def _one_part_only(self, action, plan):
        """Without a workflow these actions work on one part at a time. True if that's what was chosen."""
        if len(plan.targets) == 1:
            return True
        self._say(f"Select just one part to {action_rules.NAME[action]}. (This vault has no workflow for it, so it happens "
                  "directly, one part at a time.)", "warn")
        return False

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



