"""
request_dialog.py - asking for sign-off: the parts (Add Parts / Remove Parts), the template, a person for each
row, and the ECO's name and description when the template requires one.
"""

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox.change_orders import eco_model
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs.workflow import part_picker_dialog
from litterbox.gui.logic import error_text
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_templates


class WorkflowRequestDialog(modal_dialog.ModalDialog):
    """Start a workflow on some parts: pick a template, name a person for each sign-off, add optional extras.

        result = WorkflowRequestDialog(parent, action, parts, templates, directory, my_id, addable).show()
        # None if cancelled, else {'template': name, 'assignments': [person ids], 'extras': [(role, id)],
        #                          'reason': text, 'parts': [PN], 'eco': {'name', 'description'} or None}
    `parts` is [(PN, name)]; addable(current PNs) gives the part rows Add Parts may offer (None: no Add Parts).
    Submit asks for a last confirmation before it returns.
    """

    CHOOSE = "Choose a person..."

    def __init__(self, parent, action, parts, templates, directory, my_id, addable=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.action, self.parts, self.templates = action, list(parts), templates
        self.directory, self.my_id, self.addable = directory, my_id, addable
        self.row_vars, self.row_ids, self.extras = [], [], []
        label = workflow_templates.label_of(action)
        width, height = 980, 760
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(f"{label} workflow")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(860, 600)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)
        ctk.CTkLabel(self, text=f"{label}: start a workflow", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        self._parts_box(row=1)
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
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=5, column=0, sticky="nsew", padx=20, pady=(8, 0))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.holder = ctk.CTkScrollableFrame(body, fg_color=theme.BG_PANEL, corner_radius=10)
        self.holder.grid(row=0, column=0, sticky="nsew")
        self.holder.columnconfigure(1, weight=1)
        self._eco_form(body)
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

    @property
    def template(self):
        return self.templates[self.template_var.get()]

    # -- the parts -------------------------------------------------------------
    def _parts_box(self, row):
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=row, column=0, sticky="ew", padx=20)
        frame.columnconfigure(0, weight=1)
        self.parts_tree = ttk.Treeview(frame, columns=("pn", "name"), show="headings", height=4,
                                       selectmode="extended")
        for name, title, size in (("pn", "Part", 160), ("name", "Name", 330)):
            self.parts_tree.heading(name, text=title, anchor="w")
            self.parts_tree.column(name, width=size, anchor="w")
        self.parts_tree.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.parts_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.parts_tree.configure(yscrollcommand=scroll.set)
        side = ctk.CTkFrame(frame, fg_color="transparent")
        side.grid(row=0, column=2, sticky="n", padx=(4, 8), pady=8)
        if self.addable is not None:
            release_button.ReleaseButton(side, text="Add Parts", width=120, height=30, fg_color=theme.ACCENT,
                                         hover_color="#18527f", command=self._add_parts).grid(row=0, column=0,
                                                                                            pady=(0, 6))
        release_button.ReleaseButton(side, text="Remove Parts", width=120, height=30, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self._remove_parts).grid(row=1, column=0)
        self._fill_parts()

    def _fill_parts(self):
        self.parts_tree.delete(*self.parts_tree.get_children())
        for pn, name in self.parts:
            self.parts_tree.insert("", "end", iid=str(pn), values=(str(pn), name))

    def _add_parts(self):
        rows = self.addable([pn for pn, _name in self.parts])
        chosen = part_picker_dialog.PartPickerDialog(self, rows, workflow_templates.label_of(self.action)).show()
        if not chosen:
            return
        names = {str(r.pn): r.name for r in rows}
        have = {str(pn) for pn, _name in self.parts}
        self.parts += [(pn, names.get(str(pn), "")) for pn in chosen if str(pn) not in have]
        self._fill_parts()
        self.problem.configure(text="")

    def _remove_parts(self):
        chosen = set(self.parts_tree.selection())
        if not chosen:
            self.problem.configure(text="Select the parts to remove in the list above first.")
            return
        self.parts = [(pn, name) for pn, name in self.parts if str(pn) not in chosen]
        self._fill_parts()
        self.problem.configure(text="")

    # -- the ECO ---------------------------------------------------------------
    def _eco_form(self, parent):
        """The ECO panel, to the right of the sign-off list (hidden by _rebuild when the template needs no ECO)."""
        self.eco_frame = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=10, width=320)
        self.eco_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.eco_frame.columnconfigure(0, weight=1)
        self.eco_frame.rowconfigure(4, weight=1)
        ctk.CTkLabel(self.eco_frame, text="Engineering change order (ECO)", font=ctk.CTkFont(weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(self.eco_frame, text="Name:", anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=(4, 0))
        self.eco_name_var = tk.StringVar()
        ctk.CTkEntry(self.eco_frame, textvariable=self.eco_name_var, width=300, height=32,
                     placeholder_text="A short title for the change").grid(row=2, column=0, sticky="ew", padx=10)
        ctk.CTkLabel(self.eco_frame, text="Description:", anchor="w").grid(row=3, column=0, sticky="w", padx=10,
                                                                           pady=(6, 0))
        self.eco_description = ctk.CTkTextbox(self.eco_frame, width=300, height=70)
        self.eco_description.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def _eco(self):
        """The ECO's fields, checked, or None when the template doesn't require one. Raises EcoError."""
        if not self.template.require_eco:
            return None
        return {"name": eco_model.clean_name(self.eco_name_var.get()),
                "description": eco_model.clean_description(self.eco_description.get("1.0", "end"))}

    # -- the sign-offs ---------------------------------------------------------
    def _menu(self, parent, choices, var):
        values = [self.CHOOSE] + [label for label, _id in choices]
        return ctk.CTkOptionMenu(parent, variable=var, values=values, width=260, height=30, fg_color=theme.GRAY,
                                 button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT)

    def _rebuild(self):
        """Redraw the sign-off rows for the chosen template (extras are kept), and show the ECO form if needed."""
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
        if template.require_eco:
            self.eco_frame.grid()
        else:
            self.eco_frame.grid_remove()
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
        if not self.parts:
            self.problem.configure(text="Add at least one part (Add Parts).")
            return
        try:
            eco = self._eco()
        except eco_model.EcoError as e:
            self.problem.configure(text=str(e))
            return
        self.problem.configure(text="")
        text = task_text.request_confirm_text(self.action, self.parts, self.template, slots, reason,
                                          workflow_editing.role_warnings(self.template, self.directory), eco)
        if not messagebox.askokcancel("Start the workflow?", text, parent=self):
            return
        self.result = {"template": self.template.name, "assignments": assignments, "extras": extras,
                       "reason": reason, "parts": [pn for pn, _name in self.parts], "eco": eco}
        self.destroy()
