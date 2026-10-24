"""
project_dialog.py - the Project window: one project's name, starting digits, Lead, members (search the team, Add and
Remove), Restrict Project and Hide Project. Opened from the Projects window (projects_dialog.py) to add a project or
change one. Admins and the Owner may change everything; a project's Lead everything but its digits.
"""

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

import customtkinter as ctk

from litterbox.core import projects as project_rules
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import project_team_text
from litterbox.gui.logic import project_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button

COLORS = {"": theme.MUTED, "ok": theme.GREEN_TEXT, "warn": theme.WARN, "error": theme.ERROR}


class ProjectDialog(modal_dialog.ModalDialog):
    """Add a project (`project` None) or change one. show() gives None if cancelled, else
        {"name": text, "prefix": digits, "team": {"lead", "members", "restricted", "hidden"}}
    `others` are the other projects (the digits mustn't overlap them); `directory` is the team (None: no team, so no
    Lead or members); `digits_editable` is False for a Lead, who may change everything but the digits; `used(prefix)`
    gives the part numbers already in a block (for a new project's preview)."""
    FOCUS = "name_entry"

    def __init__(self, parent, project, others, directory, digits_editable=True, used=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.project, self.others, self.directory = project, list(others), directory
        self.used = used or (lambda prefix: [])
        self.result = None
        self.members = list(project.members) if project else []
        width, height = 720, 760 if directory is not None else 330
        self.title("Project")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.minsize(640, height if directory is None else 640)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        heading = f"Project {project.name}" if project else "New project"
        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        self._name_and_digits(row=1, digits_editable=digits_editable or project is None)
        self.preview = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40)
        self.preview.grid(row=2, column=0, sticky="ew", padx=20, pady=(6, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        if directory is not None:
            self._lead_and_switches(row=3)
            self._members(row=4)
            self.rowconfigure(4, weight=1)
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(8, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save Changes" if project else "Add Project", height=38,
                                     fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER, command=self._save).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.name_var.trace_add("write", lambda *_: self._refresh())
        self.prefix_var.trace_add("write", lambda *_: self._refresh())
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    # -- the parts of the window -----------------------------------------------
    def _name_and_digits(self, row, digits_editable):
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=row, column=0, sticky="ew", padx=20)
        form.columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text="Name", anchor="w").grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(form, text="Starts with (digits)", anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.name_var = tk.StringVar(value=self.project.name if self.project else "")
        self.prefix_var = tk.StringVar(value=self.project.prefix if self.project else "")
        self.name_entry = ctk.CTkEntry(form, textvariable=self.name_var, height=34)
        self.name_entry.grid(row=1, column=0, sticky="ew")
        ctk.CTkEntry(form, textvariable=self.prefix_var, height=34, width=140,
                     state="normal" if digits_editable else "disabled",
                     text_color=None if digits_editable else theme.MUTED).grid(row=1, column=1, padx=(10, 0))
        if not digits_editable:
            ctk.CTkLabel(form, text="Only an Admin can change the digits.", text_color=theme.MUTED,
                         anchor="e").grid(row=2, column=0, columnspan=2, sticky="e")

    def _lead_and_switches(self, row):
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 0))
        frame.columnconfigure(1, weight=1)
        project = self.project
        self.lead_choices = project_team_text.lead_choices(self.directory, project.lead if project else "")
        ctk.CTkLabel(frame, text="Project Lead:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.lead_var = tk.StringVar(value=project_team_text.lead_label(self.lead_choices,
                                                                        project.lead if project else ""))
        ctk.CTkOptionMenu(frame, variable=self.lead_var, width=260, height=32,
                          values=[project_team_text.NO_LEAD] + [label for label, _id in self.lead_choices],
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._lead_changed()).grid(row=0, column=1, sticky="w")
        self.restricted_var = tk.BooleanVar(value=bool(project and project.restricted))
        self.hidden_var = tk.BooleanVar(value=bool(project and project.hidden))
        self.restrict_box = ctk.CTkCheckBox(frame, text=project_team_text.RESTRICT_TEXT, variable=self.restricted_var,
                                            command=self._switched)
        self.restrict_box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ctk.CTkLabel(frame, text=project_team_text.RESTRICT_NOTE, text_color=theme.MUTED, anchor="w",
                     justify="left", wraplength=640).grid(row=2, column=0, columnspan=2, sticky="ew", padx=(28, 0))
        ctk.CTkCheckBox(frame, text=project_team_text.HIDE_TEXT, variable=self.hidden_var,
                        command=self._switched).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkLabel(frame, text=project_team_text.HIDE_NOTE, text_color=theme.MUTED, anchor="w",
                     justify="left", wraplength=640).grid(row=4, column=0, columnspan=2, sticky="ew", padx=(28, 0))
        self.lead_folders_var = tk.BooleanVar(value=bool(project and project.lead_only_folders))
        ctk.CTkCheckBox(frame, text=project_team_text.LEAD_FOLDERS_TEXT, variable=self.lead_folders_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ctk.CTkLabel(frame, text=project_team_text.LEAD_FOLDERS_NOTE, text_color=theme.MUTED, anchor="w",
                     justify="left", wraplength=640).grid(row=6, column=0, columnspan=2, sticky="ew", padx=(28, 0))
        self._switched()

    def _members(self, row):
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=row, column=0, sticky="nsew", padx=20, pady=(12, 0))
        frame.columnconfigure((0, 1), weight=1, uniform="m")
        frame.rowconfigure(2, weight=1)
        ctk.CTkLabel(frame, text="Members", font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        self.search_var = tk.StringVar(value="")
        search = ctk.CTkFrame(frame, fg_color="transparent")
        search.grid(row=1, column=0, sticky="ew", padx=(10, 5))
        search.columnconfigure(1, weight=1)
        ctk.CTkLabel(search, text="Search:").grid(row=0, column=0, padx=(0, 6))
        ctk.CTkEntry(search, textvariable=self.search_var, height=30).grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(frame, text="In the project", anchor="w").grid(row=1, column=1, sticky="w", padx=(5, 10))
        self.team_list = self._list(frame, "Team", row=2, column=0)
        self.member_list = self._list(frame, "Member", row=2, column=1)
        release_button.ReleaseButton(frame, text="Add", width=110, height=30, fg_color=theme.ACCENT,
                                     hover_color="#18527f", command=self._add).grid(row=3, column=0, sticky="e",
                                                                                    padx=(10, 5), pady=(6, 10))
        release_button.ReleaseButton(frame, text="Remove", width=110, height=30, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self._remove).grid(
            row=3, column=1, sticky="e", padx=(5, 10), pady=(6, 10))
        self.team_list.bind("<Double-1>", lambda event: self._add())
        self.member_list.bind("<Double-1>", lambda event: self._remove())
        self.search_var.trace_add("write", lambda *_: self._fill_lists())
        self._fill_lists()

    def _list(self, parent, title, row, column):
        tree = ttk.Treeview(parent, columns=("name",), show="headings", height=7, selectmode="extended")
        tree.heading("name", text=title, anchor="w")
        tree.column("name", width=280, stretch=True, anchor="w")
        tree.grid(row=row, column=column, sticky="nsew", padx=(10, 5) if column == 0 else (5, 10), pady=(6, 0))
        return tree

    # -- what the window does ----------------------------------------------------
    @property
    def lead(self):
        if self.directory is None:
            return ""
        return next((pid for label, pid in self.lead_choices if label == self.lead_var.get()), "")

    def _lead_changed(self):
        self.members = [m for m in self.members if m != self.lead]       # the Lead counts as a member already
        self._fill_lists()
        self.problem.configure(text="")

    def _switched(self):
        """Hide always restricts: while Hide is ticked, Restrict is ticked and can't be unticked."""
        if self.hidden_var.get():
            self.restricted_var.set(True)
            self.restrict_box.configure(state="disabled")
        else:
            self.restrict_box.configure(state="normal")
        self.problem.configure(text="")

    def _fill_lists(self):
        for tree, rows in ((self.team_list, project_team_text.addable(self.directory, self.lead, self.members,
                                                                      self.search_var.get())),
                           (self.member_list, project_team_text.member_rows(self.directory, self.members))):
            tree.delete(*tree.get_children())
            for label, pid in rows:
                tree.insert("", "end", iid=pid, values=(label,))

    def _add(self):
        chosen = [pid for pid in self.team_list.selection() if pid not in self.members]
        if not chosen:
            self.problem.configure(text="Pick people in the Team list to add (search to find them).")
            return
        self.members += chosen
        self._fill_lists()
        self.problem.configure(text="")

    def _remove(self):
        chosen = set(self.member_list.selection())
        if not chosen:
            self.problem.configure(text="Pick members in the list to remove.")
            return
        self.members = [m for m in self.members if m not in chosen]
        self._fill_lists()
        self.problem.configure(text="")

    def _refresh(self):
        prefix = self.prefix_var.get().strip()
        if self.project is not None and prefix == self.project.prefix:
            self.preview.configure(text=project_text.preview(self.name_var.get(), prefix, self.others)[0],
                                   text_color=theme.MUTED)
            return
        used = self.used(prefix) if self.project is None else ()
        text, kind = project_text.preview(self.name_var.get(), prefix, self.others, used)
        self.preview.configure(text=text, text_color=COLORS[kind])

    def team(self):
        """{lead, members, restricted, hidden, lead_only_folders} as chosen (all empty without a team)."""
        if self.directory is None:
            return {"lead": "", "members": [], "restricted": False, "hidden": False, "lead_only_folders": False}
        return {"lead": self.lead, "members": list(self.members), "restricted": bool(self.restricted_var.get()),
                "hidden": bool(self.hidden_var.get()), "lead_only_folders": bool(self.lead_folders_var.get())}

    def _save(self):
        team = self.team()
        problem = project_team_text.problem(team["lead"], team["restricted"], team["hidden"])
        if problem:
            self.problem.configure(text=problem)
            return
        try:
            project = project_rules.new_project(self.name_var.get(), self.prefix_var.get().strip(), self.others)
            project = project_rules.with_team(project, **team)
        except project_rules.ProjectError as e:
            self.problem.configure(text=str(e))
            return
        if self.project is not None and project == self.project:
            messagebox.showinfo("Project", "Nothing was changed.", parent=self)
            return
        if self.project is None and not messagebox.askyesno(
                "Project", project_text.confirm_text(project.name, project.prefix, self.used(project.prefix)),
                parent=self):
            return
        self.result = {"name": project.name, "prefix": project.prefix, "team": team}
        self.destroy()
