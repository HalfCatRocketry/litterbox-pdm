"""
request_dialog.py - asking for sign-off: choose a template and name a person for each row.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import error_text
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import release_button
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_templates


class WorkflowRequestDialog(ctk.CTkToplevel):
    """Start a workflow on some parts: pick a template, name a person for each sign-off, add optional extras.

        result = WorkflowRequestDialog(parent, action, parts, templates, directory, my_id).show()
        # None if cancelled, else {'template': name, 'assignments': [person ids], 'extras': [(role, id)],
        #                          'reason': text}
    Submit asks for a last confirmation before it returns.
    """

    CHOOSE = "Choose a person..."

    def __init__(self, parent, action, parts, templates, directory, my_id):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.action, self.parts, self.templates = action, parts, templates
        self.directory, self.my_id = directory, my_id
        self.row_vars, self.row_ids, self.extras = [], [], []
        label = workflow_templates.label_of(action)
        width, height = 680, 700
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(f"{label} workflow")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(600, 520)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        ctk.CTkLabel(self, text=f"{label}: start a workflow", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        box = ctk.CTkTextbox(self, height=min(30 + 20 * len(parts), 120), fg_color=theme.BG_PANEL)
        box.grid(row=1, column=0, sticky="ew", padx=20)
        box.insert("1.0", "\n".join(f"{pn}   {name}".rstrip() for pn, name in parts))
        box.configure(state="disabled")
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        ctk.CTkLabel(top, text="Workflow:").grid(row=0, column=0, padx=(0, 8))
        names = list(templates)
        self.template_var = tk.StringVar(value=names[0])
        ctk.CTkOptionMenu(top, variable=self.template_var, values=names, width=220, height=32, fg_color=theme.GRAY,
                          button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._rebuild()).grid(row=0, column=1)
        self.reason_var = tk.StringVar()
        if action in workflow_templates.NEEDS_REASON:
            reason = ctk.CTkFrame(self, fg_color="transparent")
            reason.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
            reason.columnconfigure(1, weight=1)
            ctk.CTkLabel(reason, text="Reason:").grid(row=0, column=0, padx=(0, 8))
            ctk.CTkEntry(reason, textvariable=self.reason_var, height=32,
                         placeholder_text=f"Why is this being {label.lower()}ed? (a few words)").grid(
                row=0, column=1, sticky="ew")
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=width - 40)
        self.note.grid(row=4, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.holder = ctk.CTkScrollableFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        self.holder.grid(row=5, column=0, sticky="nsew", padx=20, pady=(8, 0))
        self.holder.columnconfigure(1, weight=1)
        release_button.ReleaseButton(self, text="Add an optional sign-off", width=190, height=30, fg_color=theme.GRAY,
                      hover_color=theme.GRAY_HOVER, command=self._add_extra).grid(row=6, column=0, sticky="w", padx=20,
                                                                             pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=7, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Submit workflow", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._submit).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._rebuild()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    @property
    def template(self):
        return self.templates[self.template_var.get()]

    def _menu(self, parent, choices, var):
        values = [self.CHOOSE] + [label for label, _id in choices]
        return ctk.CTkOptionMenu(parent, variable=var, values=values, width=260, height=30, fg_color=theme.GRAY,
                                 button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT)

    def _rebuild(self):
        """Redraw the sign-off rows for the chosen template (extras are kept)."""
        for child in self.holder.winfo_children():
            child.destroy()
        template = self.template
        self.row_vars, self.row_ids = [], []
        for number, row in enumerate(template.rows):
            choices = task_text.row_choices(self.directory, row.roles, self.my_id, template.requester_may_sign)
            var = tk.StringVar(value=choices[0][0] if len(choices) == 1 else self.CHOOSE)
            ctk.CTkLabel(self.holder, text=row.text(), anchor="w", width=190).grid(
                row=number, column=0, sticky="w", padx=(8, 8), pady=(8 if number == 0 else 3, 0))
            self._menu(self.holder, choices, var).grid(row=number, column=1, sticky="w",
                                                       pady=(8 if number == 0 else 3, 0))
            self.row_vars.append(var)
            self.row_ids.append({label: pid for label, pid in choices})
        self._redraw_extras()
        notes = []
        if not template.allow_same_person:
            notes.append("One person can't fill more than one sign-off.")
        if not template.requester_may_sign:
            notes.append("You can't sign your own request.")
        notes += workflow_editing.role_warnings(template, self.directory)
        self.note.configure(text=" ".join(notes))

    def _redraw_extras(self):
        for child in list(getattr(self, "extra_frames", [])):
            child.destroy()
        self.extra_frames = []
        start = len(self.row_vars)
        for number, extra in enumerate(self.extras):
            frame = ctk.CTkFrame(self.holder, fg_color="transparent")
            frame.grid(row=start + number, column=0, columnspan=2, sticky="w", padx=8, pady=(3, 0))
            self.extra_frames.append(frame)
            ctk.CTkOptionMenu(frame, variable=extra["role"], values=self.directory.roles or [extra["role"].get()],
                              width=180, height=30, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                              button_hover_color=theme.ACCENT,
                              command=lambda value, e=extra: self._extra_role(e)).grid(row=0, column=0, padx=(0, 8))
            choices = task_text.row_choices(self.directory, [extra["role"].get()])
            extra["ids"] = {label: pid for label, pid in choices}
            self._menu(frame, choices, extra["person"]).grid(row=0, column=1)
            release_button.ReleaseButton(frame, text="Remove", width=76, height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                          command=lambda e=extra: self._remove_extra(e)).grid(row=0, column=2, padx=(8, 0))

    def _add_extra(self):
        if not self.directory.roles:
            return
        self.extras.append({"role": tk.StringVar(value=self.directory.roles[0]), "person": tk.StringVar(
            value=self.CHOOSE), "ids": {}})
        self._redraw_extras()

    def _extra_role(self, extra):
        extra["person"].set(self.CHOOSE)
        self._redraw_extras()

    def _remove_extra(self, extra):
        self.extras.remove(extra)
        self._redraw_extras()

    def _submit(self):
        assignments = [ids.get(var.get(), "") for var, ids in zip(self.row_vars, self.row_ids)]
        extras = [(e["role"].get(), e["ids"].get(e["person"].get(), "")) for e in self.extras]
        reason = " ".join(self.reason_var.get().split())
        try:
            slots = signoff_slots.build_slots(self.template, self.directory, self.my_id, assignments, extras)
        except workflow_templates.WorkflowError as e:
            self.problem.configure(text=error_text.shorten(str(e)))
            return
        if self.action in workflow_templates.NEEDS_REASON and not reason:
            self.problem.configure(text="A reason is required.")
            return
        self.problem.configure(text="")
        text = task_text.request_confirm_text(self.action, self.parts, self.template, slots, reason,
                                          workflow_editing.role_warnings(self.template, self.directory))
        if not messagebox.askokcancel("Start the workflow?", text, parent=self):
            return
        self.result = {"template": self.template.name, "assignments": assignments, "extras": extras,
                       "reason": reason}
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result
