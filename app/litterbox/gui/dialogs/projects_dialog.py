"""
projects_dialog.py - Projects: the org's projects that you may see, each with its Lead, members and whether it is
restricted or hidden. Admins and the Owner may add (New Project), change and delete any, and anyone on the team may
add one when the org allows it (core/project_settings.py); a project's Lead may change that project (project_dialog.py
has the window for one project).
"""

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.core import projects as project_rules
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import project_dialog
from litterbox.gui.logic import project_team_text
from litterbox.gui.logic import project_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.team import project_access
from litterbox.vault import config
from litterbox.vault import project_admin


class ProjectsDialog(modal_dialog.ModalDialog):
    """The projects, with Edit and Delete beside each where you may, and New Project for Admins.
    show() gives what to do, or None:
        ("add", name, prefix, team, short_ok)   ("edit", old name, new name, new prefix, team, short_ok)
        ("delete", name)
    `team` is {lead, members, restricted, hidden}. `person` is you on the team (None with no team); `legacy` is a
    vault with no team, where everyone may do everything. What a change or a delete does to the parts is worked out
    and asked about after this window closes. `may_add`: New Project is offered to someone who isn't an Admin;
    `min_digits` is the org's fewest starting digits (short_ok: an Admin was warned and went ahead)."""

    def __init__(self, parent, repo, projects, directory=None, person=None, legacy=True, may_add=False, min_digits=0):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.repo, self.directory, self.person, self.legacy = repo, directory, person, legacy
        self.all_projects = list(projects)
        self.projects = project_access.visible(person, projects, legacy)
        self.admin = legacy or project_access.overrides(person)
        self.may_add, self.min_digits = self.admin or may_add, min_digits
        self.result = None
        width, height = 640, 520
        self.title("Projects")
        window_chrome.place_over(self, parent, width, height, down=4)
        window_chrome.min_size(self, 560, 400)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text="Projects", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
        ctk.CTkLabel(self, text="A project owns every part number that starts with its digits. Choosing it in New "
                                "Part takes the next free number there; parts with no project never use them.",
                     anchor="w", justify="left", wraplength=width - 40, text_color=theme.MUTED).grid(
            row=1, column=0, sticky="ew", padx=20, pady=(2, 8))
        listing = ctk.CTkScrollableFrame(self)
        listing.grid(row=2, column=0, sticky="nsew", padx=20)
        listing.columnconfigure(0, weight=1)
        if not self.projects:
            ctk.CTkLabel(listing, text=project_text.project_lines([])[0], text_color=theme.MUTED, anchor="w").grid(
                row=0, column=0, sticky="ew")
        for row, (project, line) in enumerate(zip(self.projects, project_text.project_lines(self.projects))):
            team = project_team_text.team_line(directory, project)
            ctk.CTkLabel(listing, text=line + (f"\n{team}" if team else ""), anchor="w", justify="left").grid(
                row=row, column=0, sticky="ew", pady=3)
            if project_access.may_edit(person, project, legacy):
                release_button.ReleaseButton(listing, text="Edit", width=64, height=28, fg_color=theme.GRAY,
                                             hover_color=theme.GRAY_HOVER,
                                             command=lambda p=project: self._edit(p)).grid(row=row, column=1,
                                                                                           padx=(6, 0))
            if self.admin:
                release_button.ReleaseButton(listing, text="Delete", width=64, height=28, fg_color=theme.GRAY,
                                             hover_color=theme.GRAY_HOVER,
                                             command=lambda p=project: self._delete(p)).grid(row=row, column=2,
                                                                                             padx=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(14, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Close", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        if self.may_add:
            release_button.ReleaseButton(buttons, text="New Project...", height=38, fg_color=theme.GREEN,
                                         hover_color=theme.GREEN_HOVER, command=self._new).grid(
                row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _used(self, prefix):
        """The part numbers already in the block these digits would give (none if the digits can't be used)."""
        try:
            return project_admin.parts_in_block(self.repo, prefix)
        except (LitterboxError, config.ConfigError, project_rules.ProjectError):
            return []

    def _window(self, project):
        others = [p for p in self.all_projects if p is not project]
        return project_dialog.ProjectDialog(self, project, others, self.directory, digits_editable=self.admin,
                                            used=self._used, min_digits=self.min_digits, admin=self.admin,
                                            me=self.person.id if self.person is not None else "")

    def _new(self):
        chosen = self._window(None).show()
        if chosen:
            self.result = ("add", chosen["name"], chosen["prefix"], chosen["team"], chosen["short_ok"])
            self.destroy()

    def _edit(self, project):
        chosen = self._window(project).show()
        if chosen:
            self.result = ("edit", project.name, chosen["name"], chosen["prefix"], chosen["team"], chosen["short_ok"])
            self.destroy()

    def _delete(self, project):
        self.result = ("delete", project.name)
        self.destroy()
