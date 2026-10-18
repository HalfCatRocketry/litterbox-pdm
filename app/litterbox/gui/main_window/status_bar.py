"""
status_bar.py - the line along the bottom of the main window: a coloured dot and word for the job queue (green
Ready, yellow Working, red Error, see jobs/job_queue.py), what just happened, and on the right what SolidWorks has
open, the jobs waiting, and the log. On an error it shows Details... and Dismiss. The log opens as a drawer above it.
"""

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.widgets import menu_bar
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import tooltip
from litterbox.jobs import job_queue as jobs

STATE_COLORS = {jobs.READY: theme.GREEN, jobs.WORKING: theme.BANNER_YELLOW, jobs.ERROR: theme.RED}


TONE_COLORS = {"normal": theme.MUTED, "warn": theme.WARN, "error": theme.ERROR}


class StatusBar:
    """the status bar and the log drawer (a part of the main window, App)."""

    def _build_status_bar(self):
        self.log_box = ctk.CTkTextbox(self, height=150, fg_color=theme.BG_PANEL, text_color=theme.MUTED,
                                      font=ctk.CTkFont(family="Consolas", size=12), corner_radius=0)
        self.log_box.configure(state="disabled")
        self.log_shown = False
        bar = self.status_bar = ctk.CTkFrame(self, fg_color=theme.BG_BAR, corner_radius=0, height=30)
        bar.grid(row=4, column=0, sticky="ew")
        bar.columnconfigure(2, weight=1)
        self.status_dot = ctk.CTkFrame(bar, width=12, height=12, corner_radius=6, fg_color=theme.GREEN)
        self.status_dot.grid(row=0, column=0, padx=(12, 6), pady=8)
        self.status_state = ctk.CTkLabel(bar, text="Ready", font=ctk.CTkFont(size=13, weight="bold"), anchor="w")
        self.status_state.grid(row=0, column=1, sticky="w", padx=(0, 10))
        tooltip.Tooltip(self.status_state, lambda: self.jobs.banner().detail)
        self.status = ctk.CTkLabel(bar, text="Ready", text_color=theme.MUTED, anchor="w")
        self.status.grid(row=0, column=2, sticky="ew")
        tooltip.Tooltip(self.status, lambda: self.status.cget("text") if len(self.status.cget("text")) > 60 else "")
        self.error_details_button = release_button.ReleaseButton(bar, text="Details...", width=80, height=24,
                                                                 fg_color="white", text_color=theme.RED,
                                                                 hover_color="#e8e8e8", command=self.show_errors)
        self.error_dismiss_button = release_button.ReleaseButton(bar, text="Dismiss", width=70, height=24,
                                                                 fg_color="transparent", border_width=1,
                                                                 border_color="white", text_color="white",
                                                                 hover_color=theme.RED_HOVER, command=self.dismiss_errors)
        self.solidworks_label = ctk.CTkLabel(bar, text="", text_color=theme.MUTED, anchor="e")
        self.solidworks_label.grid(row=0, column=5, padx=(10, 6))
        tooltip.Tooltip(self.solidworks_label, "Litterbox watches what SolidWorks has open, to warn before a check-in "
                                               "or download would clash with it (solidworks_watch in settings.yaml).")
        self.jobs_button = ctk.CTkButton(bar, text="Jobs", width=70, height=24, fg_color="transparent",
                                         hover_color=theme.BG_HOVER, text_color=theme.MUTED, command=self._show_jobs)
        self.jobs_button.grid(row=0, column=6, padx=(0, 4))
        tooltip.Tooltip(self.jobs_button, "What Litterbox is doing, and what is waiting its turn.")
        self.log_button = ctk.CTkButton(bar, text="Log ▴", width=70, height=24, fg_color="transparent",
                                        hover_color=theme.BG_HOVER, text_color=theme.MUTED, command=self.toggle_log)
        self.log_button.grid(row=0, column=7, padx=(0, 10))
        tooltip.Tooltip(self.log_button, "Every git command and message, for troubleshooting.")

    def toggle_log(self):
        """Open or close the log drawer above the status bar."""
        self.log_shown = not self.log_shown
        if self.log_shown:
            self.log_box.grid(row=3, column=0, sticky="ew")
            self.log_box.see("end")
        else:
            self.log_box.grid_remove()
        self.log_button.configure(text="Log ▾" if self.log_shown else "Log ▴")

    def _update_banner(self):
        """Bring the dot, the word and the error buttons up to date with the job queue."""
        state = self.jobs.banner()
        self.status_dot.configure(fg_color=STATE_COLORS[state.kind])
        self.status_state.configure(text=state.title if state.kind != jobs.WORKING else f"Working: {state.detail}",
                                    text_color=theme.ERROR if state.kind == jobs.ERROR else theme.TEXT)
        if state.kind == jobs.ERROR:
            self.status_bar.configure(fg_color=theme.RED)
            self.error_details_button.grid(row=0, column=3, padx=(6, 4))
            self.error_dismiss_button.grid(row=0, column=4, padx=(0, 6))
            self.status_state.configure(text_color="white")
        else:
            self.status_bar.configure(fg_color=theme.BG_BAR)
            self.error_details_button.grid_remove()
            self.error_dismiss_button.grid_remove()
        waiting = len(self.jobs.snapshot()) if hasattr(self.jobs, "snapshot") else 0
        self.jobs_button.configure(text=f"Jobs ({waiting})" if waiting else "Jobs")

    def _show_jobs(self):
        """A list of what is running and what is waiting, under the Jobs button."""
        menu = menu_bar.dark_menu(self)
        entries = self.jobs.snapshot()
        names = {"running": "Running", "queued": "Waiting", "finishing": "Finishing"}
        for label, state in entries:
            menu.add_command(label=f"{names.get(state, state)}:  {label}", state="disabled")
        if not entries:
            menu.add_command(label="Nothing is running.", state="disabled")
        menu_bar.open_below(menu, self.jobs_button)

    def _show_solidworks(self, snapshot):
        """The status bar's note of what SolidWorks has open (blank when Litterbox isn't watching)."""
        if snapshot is None:
            self.solidworks_label.configure(text="")
            return
        count = len(snapshot)                        # {path key: OpenDocument}, see sw_watcher.py
        self.solidworks_label.configure(text=f"SolidWorks: {count} open" if count else "SolidWorks: nothing open")

    def _log(self, text):
        from litterbox.user import settings
        settings.append_log(text)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _say(self, text, tone="normal"):
        """Put a message in the status bar (and on the Team screen, if it is open, so you see a click did
        something there)."""
        self.status.configure(text=text, text_color=TONE_COLORS[tone])
        for window in self._team_windows():
            window.say(text, tone)
