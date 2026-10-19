"""
projects_dialog.py - Projects (Admin and Owner): the org's projects, and adding, editing or deleting one (a name and
the digits its part numbers start with).
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.core import projects as project_rules
from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import project_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.vault import config
from litterbox.vault import project_admin

COLORS = {"": theme.MUTED, "ok": theme.GREEN_TEXT, "warn": theme.WARN, "error": theme.ERROR}


class ProjectsDialog(modal_dialog.ModalDialog):
    """The projects, with Edit and Delete beside each, and a form to add one (or change the one being edited).
    show() gives what to do, or None:
        ("add", name, prefix)   ("edit", old name, new name, new prefix)   ("delete", name)
    What a change or a delete does to the parts is worked out and asked about after this window closes."""
    FOCUS = "name_entry"

    def __init__(self, parent, repo, projects):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.repo, self.projects = repo, list(projects)
        self.result, self.editing = None, None
        width, height = 600, 580
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title("Projects")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Projects", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
        ctk.CTkLabel(self, text="A project owns every part number that starts with its digits. Choosing it in New "
                                "Part takes the next free number there; parts with no project never use them.",
                     anchor="w", justify="left", wraplength=width - 40, text_color=theme.MUTED).grid(
            row=1, column=0, sticky="ew", padx=20, pady=(2, 8))
        listing = ctk.CTkScrollableFrame(self, height=150)
        listing.grid(row=2, column=0, sticky="ew", padx=20)
        listing.columnconfigure(0, weight=1)
        if not self.projects:
            ctk.CTkLabel(listing, text=project_text.project_lines([])[0], text_color=theme.MUTED, anchor="w").grid(
                row=0, column=0, sticky="ew")
        for row, (project, line) in enumerate(zip(self.projects, project_text.project_lines(self.projects))):
            ctk.CTkLabel(listing, text=line, anchor="w").grid(row=row, column=0, sticky="ew", pady=2)
            release_button.ReleaseButton(listing, text="Edit", width=64, height=28, fg_color=theme.GRAY,
                          hover_color=theme.GRAY_HOVER, command=lambda p=project: self._edit(p)).grid(
                row=row, column=1, padx=(6, 0))
            release_button.ReleaseButton(listing, text="Delete", width=64, height=28, fg_color=theme.GRAY,
                          hover_color=theme.GRAY_HOVER, command=lambda p=project: self._delete(p)).grid(
                row=row, column=2, padx=(6, 0))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=3, column=0, sticky="ew", padx=20, pady=(14, 2))
        top.columnconfigure(0, weight=1)
        self.form_title = ctk.CTkLabel(top, text="New project", font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        self.form_title.grid(row=0, column=0, sticky="ew")
        self.stop_button = release_button.ReleaseButton(top, text="New project instead", width=150, height=28,
                                         fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER, command=self._stop_editing)
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=4, column=0, sticky="ew", padx=20)
        form.columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text="Name", anchor="w").grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(form, text="Starts with (digits)", anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 0))
        self.name_var, self.prefix_var = tk.StringVar(), tk.StringVar()
        self.name_entry = ctk.CTkEntry(form, textvariable=self.name_var, height=34)
        self.name_entry.grid(row=1, column=0, sticky="ew")
        ctk.CTkEntry(form, textvariable=self.prefix_var, height=34, width=140).grid(row=1, column=1, padx=(10, 0))
        self.preview = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=width - 40)
        self.preview.grid(row=5, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.note = ctk.CTkLabel(self, text="", text_color=theme.WARN, anchor="w", justify="left",
                                 wraplength=width - 40)
        self.note.grid(row=6, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.name_var.trace_add("write", lambda *_: self._refresh())
        self.prefix_var.trace_add("write", lambda *_: self._refresh())

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=7, column=0, sticky="ew", padx=20, pady=(14, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Close", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.save_button = release_button.ReleaseButton(buttons, text="Add Project", height=38, fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER, command=self._save)
        self.save_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self._stop_editing()
        self.after(150, self._grab)

    def _others(self):
        """The projects the one in the form must not clash with (all of them, less the one being edited)."""
        return [p for p in self.projects if p is not self.editing]

    def _edit(self, project):
        self.editing = project
        self.form_title.configure(text=f"Edit {project.name}")
        self.stop_button.grid(row=0, column=1)
        self.save_button.configure(text="Save Changes")
        self.note.configure(text=project_text.EDIT_NOTE)
        self.name_var.set(project.name)
        self.prefix_var.set(project.prefix)

    def _stop_editing(self):
        self.editing = None
        self.form_title.configure(text="New project")
        self.stop_button.grid_forget()
        self.save_button.configure(text="Add Project")
        self.note.configure(text=project_text.ADD_NOTE)
        self.name_var.set("")
        self.prefix_var.set("")

    def _used(self, prefix):
        """The part numbers already in the block these digits would give (none if the digits can't be used)."""
        try:
            return project_admin.parts_in_block(self.repo, prefix)
        except (LitterboxError, config.ConfigError, project_rules.ProjectError):
            return []

    def _refresh(self):
        prefix = self.prefix_var.get().strip()
        used = () if self.editing else self._used(prefix)       # an edit's parts are listed before it is done
        text, kind = project_text.preview(self.name_var.get(), prefix, self._others(), used)
        self.preview.configure(text=text, text_color=COLORS[kind])

    def _save(self):
        name, prefix = self.name_var.get(), self.prefix_var.get().strip()
        try:
            project = project_rules.new_project(name, prefix, self._others())
        except project_rules.ProjectError as e:
            messagebox.showwarning("Projects", str(e), parent=self)
            return
        if self.editing is not None:
            if project == self.editing:
                messagebox.showinfo("Projects", "Nothing was changed.", parent=self)
                return
            self.result = ("edit", self.editing.name, project.name, project.prefix)
        else:
            if not messagebox.askyesno("Projects", project_text.confirm_text(project.name, project.prefix,
                                                                              self._used(project.prefix)), parent=self):
                return
            self.result = ("add", project.name, project.prefix)
        self.destroy()

    def _delete(self, project):
        self.result = ("delete", project.name)
        self.destroy()
