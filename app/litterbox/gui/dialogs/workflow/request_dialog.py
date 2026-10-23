"""
request_dialog.py - asking for sign-off: the parts (Add Parts / Remove Parts, and when the request needs an ECO,
for a release of Rev B or later or a void, what changed and the Dispo of each), the template, a person for each
row, and the ECO's title and description when the request needs one. It also changes a rejected request (a draft) for resubmitting.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.change_orders import eco_model
from litterbox.core.revision_letters import FIRST_REVISION
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs.workflow import part_picker_dialog
from litterbox.gui.logic import change_text
from litterbox.gui.logic import error_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import change_table
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_ecos
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_templates

SIGNOFF_WIDTH = 470             # the sign-off list beside an ECO: just room for its rows; the ECO takes the rest
EXTRAS_WIDTH = 560              # ... and for an extra sign-off's row (role, person, Remove)


def as_part(part):
    """(PN, name, revision, released revision) from that or from (PN, name) (taken as a first release)."""
    part = tuple(part)
    return part if len(part) == 4 else (part[0], part[1], FIRST_REVISION, "")


class WorkflowRequestDialog(modal_dialog.ModalDialog):
    """Start a workflow on some parts: pick a template, name a person for each sign-off, add optional extras.

        result = WorkflowRequestDialog(parent, action, parts, templates, directory, my_id, addable).show()
        # None if cancelled, else {'template': name, 'assignments': [person ids], 'extras': [(role, id)],
        #                          'reason': text, 'parts': [PN], 'eco': {'name', 'description'} or None,
        #                          'changes': {part number text: {'changed', 'disposition'}} or None (no ECO)}
    `parts` is [(PN, name, revision, released revision)]; addable(current PNs) gives the part rows Add Parts may
    offer (None: no Add Parts). Submit asks for a last confirmation before it returns.

    With `draft` (a rejected request: {'template', 'people', 'extras', 'reason', 'eco', 'changes', 'rejected'}),
    it starts filled in as it was asked, says why it was rejected, and offers Withdraw (result {'withdraw': True})
    beside Resubmit.
    """

    CHOOSE = "Choose a person..."

    def __init__(self, parent, action, parts, templates, directory, my_id, addable=None, draft=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.action, self.templates, self.draft = action, templates, draft
        self.directory, self.my_id, self.addable = directory, my_id, addable
        self.row_vars, self.row_ids, self.extras = [], [], []
        label = workflow_templates.label_of(action)
        width, height = 1060, 800
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title(f"{label} workflow")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(900, 620)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        heading = f"{label}: change and resubmit" if draft else f"{label}: start a workflow"
        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        if draft:
            ctk.CTkLabel(self, text=task_text.rejection_text(draft.get("rejected") or {}), text_color=theme.ERROR,
                         anchor="w", justify="left", wraplength=width - 40).grid(row=1, column=0, sticky="ew",
                                                                                  padx=20, pady=(0, 6))
        self._parts_box([as_part(p) for p in parts], row=2)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 0))
        ctk.CTkLabel(top, text="Workflow:").grid(row=0, column=0, padx=(0, 8))
        names = list(templates)
        first = (draft or {}).get("template")
        self.template_var = tk.StringVar(value=first if first in templates else names[0])
        ctk.CTkOptionMenu(top, variable=self.template_var, values=names, width=220, height=32, fg_color=theme.GRAY,
                          button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._rebuild()).grid(row=0, column=1)
        self.reason_var = tk.StringVar(value=(draft or {}).get("reason", ""))
        if action in workflow_templates.NEEDS_REASON:
            reason = ctk.CTkFrame(self, fg_color="transparent")
            reason.grid(row=4, column=0, sticky="ew", padx=20, pady=(8, 0))
            reason.columnconfigure(1, weight=1)
            ctk.CTkLabel(reason, text="Reason:").grid(row=0, column=0, padx=(0, 8))
            ctk.CTkEntry(reason, textvariable=self.reason_var, height=32,
                         placeholder_text=f"Why is this being {label.lower()}ed? (a few words)").grid(
                row=0, column=1, sticky="ew")
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=width - 40)
        self.note.grid(row=5, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=6, column=0, sticky="nsew", padx=20, pady=(8, 0))
        self.rowconfigure(6, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.holder = ctk.CTkScrollableFrame(self.body, fg_color=theme.BG_PANEL, corner_radius=10, width=SIGNOFF_WIDTH)
        self.holder.grid(row=0, column=0, sticky="nsew")
        self.holder.columnconfigure(1, weight=1)
        self._eco_form(self.body)
        release_button.ReleaseButton(self, text="Add an optional sign-off", width=190, height=30, fg_color=theme.GRAY,
                      hover_color=theme.GRAY_HOVER, command=self._add_extra).grid(row=7, column=0, sticky="w", padx=20,
                                                                             pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=8, column=0, sticky="ew", padx=20, pady=(4, 0))
        self._buttons(row=9)
        self._rebuild()
        if draft:
            self._fill_from_draft(draft)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _buttons(self, row):
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=row, column=0, sticky="ew", padx=20, pady=(6, 18))
        columns = (0, 1, 2) if self.draft else (0, 1)
        buttons.columnconfigure(columns, weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        if self.draft:
            release_button.ReleaseButton(buttons, text="Withdraw", height=38, fg_color=theme.RED,
                                         hover_color=theme.RED_HOVER, command=self._withdraw).grid(
                row=0, column=1, sticky="ew", padx=6)
        release_button.ReleaseButton(buttons, text="Resubmit workflow" if self.draft else "Submit workflow", height=38,
                                     fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER, command=self._submit).grid(
            row=0, column=columns[-1], sticky="ew", padx=(6, 0))

    @property
    def template(self):
        return self.templates[self.template_var.get()]

    @property
    def parts(self):
        """[(PN, name, revision, released revision)] in the request."""
        return list(self.table.parts)

    # -- the parts -------------------------------------------------------------
    def _parts_box(self, parts, row):
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=row, column=0, sticky="ew", padx=20)
        frame.columnconfigure(0, weight=1)
        self.table = change_table.ChangeTable(frame, self.action, parts, (self.draft or {}).get("changes"),
                                              on_change=lambda: self.problem.configure(text=""))
        self.parts_tree = self.table.tree
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
        if workflow_templates.base_action(self.action) in (workflow_templates.RELEASE, workflow_templates.VOID):
            self.change_hint = ctk.CTkLabel(side, text=task_text.CHANGE_HINT, text_color=theme.MUTED, justify="left",
                                            wraplength=130, anchor="w")
            self.change_hint.grid(row=2, column=0, sticky="w", pady=(10, 0))

    def _add_parts(self):
        rows = self.addable([p[0] for p in self.parts])
        chosen = part_picker_dialog.PartPickerDialog(self, rows, workflow_templates.label_of(self.action)).show()
        if not chosen:
            return
        found = {str(r.pn): r for r in rows}
        have = {str(p[0]) for p in self.parts}
        added = []
        for pn in chosen:
            row = found.get(str(pn))
            if str(pn) not in have:
                added.append((pn, getattr(row, "name", ""), getattr(row, "revision", FIRST_REVISION),
                              getattr(row, "released_revision", "")))
        self.table.set_parts(self.parts + added)
        self._show_eco()
        self.problem.configure(text="")

    def _remove_parts(self):
        chosen = set(self.table.selection())
        if not chosen:
            self.problem.configure(text="Select the parts to remove in the list above first.")
            return
        self.table.set_parts([p for p in self.parts if str(p[0]) not in chosen])
        self._show_eco()
        self.problem.configure(text="")

    # -- the ECO ---------------------------------------------------------------
    def _eco_form(self, parent):
        """The ECO panel, to the right of the sign-off list (hidden by _show_eco when the request needs no ECO)."""
        self.eco_frame = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=10, width=320)
        self.eco_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.eco_frame.columnconfigure(0, weight=1)
        self.eco_frame.rowconfigure(4, weight=1)
        ctk.CTkLabel(self.eco_frame, text="Engineering change order (ECO)", font=ctk.CTkFont(weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(self.eco_frame, text="Title:", anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=(4, 0))
        eco = (self.draft or {}).get("eco") or {}
        self.eco_name_var = tk.StringVar(value=eco.get("name", ""))
        ctk.CTkEntry(self.eco_frame, textvariable=self.eco_name_var, width=300, height=32,
                     placeholder_text="A short title for the change").grid(row=2, column=0, sticky="ew", padx=10)
        ctk.CTkLabel(self.eco_frame, text="Description:", anchor="w").grid(row=3, column=0, sticky="w", padx=10,
                                                                           pady=(6, 0))
        self.eco_description = ctk.CTkTextbox(self.eco_frame, width=300, height=70)
        self.eco_description.grid(row=4, column=0, sticky="nsew", padx=10, pady=(0, 10))
        if eco.get("description"):
            self.eco_description.insert("1.0", eco["description"])

    def eco_needed(self):
        """True if this request needs an ECO: the template requires one and it isn't a release of parts all at Rev A."""
        return workflow_ecos.eco_needed(self.template, self.action, [p[2] for p in self.parts])

    def _show_eco(self):
        """Show the ECO panel when it is needed, with the sign-offs just wide enough beside it; else the sign-offs
        take the whole width. Form, Fit, Function and Dispo are asked only with an ECO."""
        needed = self.eco_needed()
        self.table.ask_changes(needed)
        hint = getattr(self, "change_hint", None)
        if needed:
            if hint is not None:
                hint.grid()
            self.eco_frame.grid()
            self.body.columnconfigure(0, weight=0)
            self.body.columnconfigure(1, weight=1)
        else:
            if hint is not None:
                hint.grid_remove()
            self.eco_frame.grid_remove()
            self.body.columnconfigure(0, weight=1)
            self.body.columnconfigure(1, weight=0)

    def _eco(self):
        """The ECO's fields, checked, or None when the request needs none. Raises EcoError."""
        if not self.eco_needed():
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
        self._show_eco()
        notes = []
        if not template.allow_same_person:
            notes.append("One person can't fill more than one sign-off.")
        if not template.requester_may_sign:
            notes.append("You can't sign your own request.")
        notes += workflow_editing.role_warnings(template, self.directory)
        self.note.configure(text=" ".join(notes))

    def _fill_from_draft(self, draft):
        """Pick the people the rejected request named, where the template still has those rows."""
        for var, ids, pid in zip(self.row_vars, self.row_ids, draft.get("people") or []):
            label = next((name for name, each in ids.items() if each == pid), None)
            if label:
                var.set(label)
        for role, pid in draft.get("extras") or []:
            choices = task_text.row_choices(self.directory, [role])
            label = next((name for name, each in choices if each == pid), self.CHOOSE)
            self.extras.append({"role": tk.StringVar(value=role), "person": tk.StringVar(value=label), "ids": {}})
        self._redraw_extras()

    def _redraw_extras(self):
        for child in list(getattr(self, "extra_frames", [])):
            child.destroy()
        self.extra_frames = []
        start = len(self.row_vars)
        self.holder.configure(width=EXTRAS_WIDTH if self.extras else SIGNOFF_WIDTH)
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

    # -- the answer ------------------------------------------------------------
    def _withdraw(self):
        if messagebox.askyesno("Withdraw", "Withdraw this request for good? Its ECO, if it has one, is closed as "
                                           "withdrawn, and the parts are left as they are.", parent=self):
            self.result = {"withdraw": True}
            self.destroy()

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
        missing = self.table.missing()
        if missing:
            self.problem.configure(text=change_text.missing_text(missing))
            return
        try:
            eco = self._eco()
        except eco_model.EcoError as e:
            self.problem.configure(text=str(e))
            return
        self.problem.configure(text="")
        parts = [(p[0], p[1]) for p in self.parts]
        text = task_text.request_confirm_text(self.action, parts, self.template, slots, reason,
                                              workflow_editing.role_warnings(self.template, self.directory), eco,
                                              resubmit=bool(self.draft))
        if not messagebox.askokcancel("Resubmit the workflow?" if self.draft else "Start the workflow?", text,
                                      parent=self):
            return
        self.result = {"template": self.template.name, "assignments": assignments, "extras": extras,
                       "reason": reason, "parts": [p[0] for p in self.parts], "eco": eco,
                       "changes": self.table.result()}
        self.destroy()


def draft_of(task, eco=None, local=True):
    """What WorkflowRequestDialog's `draft` takes, from a rejected request's task (workflow_tasks.Task) and its
    ECO (change_orders/eco_model.Eco, or None)."""
    people = [s["id"] for s in task.slots if not s.get("extra")]
    extras = [(s["roles"][0], s["id"]) for s in task.slots if s.get("extra") and s.get("roles")]
    rejected = dict(task.rejected, at=history_text.to_display_time(task.rejected.get("at", ""), local))
    return {"template": task.template_name, "people": people, "extras": extras, "reason": task.reason,
            "eco": {"name": eco.name, "description": eco.description} if eco is not None else None,
            "changes": {pn: dict(change) for pn, change in task.changes.items()}, "rejected": rejected}
