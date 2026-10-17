"""
workflows_dialog.py - the Workflows window: the sign-off templates of each action (uses
gui/logic/workflow_editor.py for the working copy).
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.logic import workflow_editor
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.workflows import workflow_templates


class WorkflowsDialog(modal_dialog.ModalDialog):
    """Team > Workflows: the sign-off templates for each action, one tab per action.

        WorkflowsDialog(parent, roles, templates, apply=callback).show()
        # callback(ops, editor) -> problem text, or "" when the change was taken (see workflow_editor.WorkflowEditor)

    A template is a list of sign-offs. A role listed twice is two sign-offs; "+ or" lets a sign-off be filled by
    someone with any of several roles. Nothing is saved here: OK keeps the change in the Team window's draft.
    """

    def __init__(self, parent, roles, templates, apply=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.apply = apply
        self.roles = list(roles)
        self.editor = workflow_editor.WorkflowEditor(templates)
        self.selected = {action: 0 for action in workflow_templates.ACTIONS}
        self.name_vars = {}
        width, height = 820, 640
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Workflows")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(720, 520)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Workflows: who has to sign off before something happens. An action with no "
                                "workflow just happens.", text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=width - 40).grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 6))
        self.panes = {}
        for action in workflow_templates.ACTIONS:
            tab = self.tabs.add(workflow_templates.label_of(action))
            tab.columnconfigure(0, weight=1)
            tab.rowconfigure(2, weight=1)
            self.panes[action] = tab
            self._redraw(action)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=2, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 16))
        buttons.columnconfigure(0, weight=1)
        release_button.ReleaseButton(buttons, text="Add standard workflows", width=190, height=38, fg_color=theme.PURPLE,
                      hover_color=theme.PURPLE_HOVER, command=self._standard).grid(row=0, column=0, sticky="w")
        release_button.ReleaseButton(buttons, text="Cancel", width=110, height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=1, padx=(6, 6))
        release_button.ReleaseButton(buttons, text="OK", width=110, height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=2)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _cancel(self):
        if self.editor.dirty and not confirm_dialogs.ask_discard(self, "your changes to the workflows"):
            return
        self.destroy()

    # -- drawing -----------------------------------------------------------
    def _redraw(self, action):
        pane = self.panes[action]
        for child in pane.winfo_children():
            child.destroy()
        names = self.editor.names(action)
        index = min(self.selected[action], max(len(names) - 1, 0))
        self.selected[action] = index
        top = ctk.CTkFrame(pane, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        label = workflow_templates.label_of(action)
        if not names:
            ctk.CTkLabel(top, text=f"No {label} workflow, so {label.lower()} just happens.", text_color=theme.MUTED,
                         anchor="w").grid(row=0, column=0, padx=(0, 10), pady=4)
        else:
            self.selected_var = tk.StringVar(value=names[index])
            ctk.CTkOptionMenu(top, variable=self.selected_var, values=names, width=200, height=32, fg_color=theme.GRAY,
                              button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                              command=lambda value, a=action: self._select(a, value)).grid(row=0, column=0,
                                                                                         padx=(0, 6), pady=4)
        release_button.ReleaseButton(top, text="New workflow", width=120, height=32, fg_color=theme.ACCENT, hover_color="#18527f",
                      command=lambda: self._new(action)).grid(row=0, column=1, padx=(0, 6))
        if names:
            release_button.ReleaseButton(top, text="Delete", width=80, height=32, fg_color=theme.RED, hover_color=theme.RED_HOVER,
                          command=lambda: self._delete(action)).grid(row=0, column=2)
            name_row = ctk.CTkFrame(pane, fg_color="transparent")
            name_row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
            ctk.CTkLabel(name_row, text="Name:", text_color=theme.MUTED).grid(row=0, column=0, padx=(0, 6))
            var = tk.StringVar(value=names[index])
            self.name_vars[action] = var
            var.trace_add("write", lambda *_: self._rename(action, var.get()))
            ctk.CTkEntry(name_row, textvariable=var, width=220, height=30).grid(row=0, column=1)
            holder = ctk.CTkScrollableFrame(pane, fg_color=theme.BG_PANEL, corner_radius=10)
            holder.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
            item = self.editor.items[action][index]
            for number, roles in enumerate(item["rows"]):
                self._draw_row(holder, action, index, number, roles)
            foot = ctk.CTkFrame(pane, fg_color="transparent")
            foot.grid(row=3, column=0, sticky="ew", pady=(8, 0))
            release_button.ReleaseButton(foot, text="Add a sign-off", width=130, height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                          command=lambda: self._add_row(action, index)).grid(row=0, column=0, sticky="w")
            same = tk.BooleanVar(value=item["same"])
            req = tk.BooleanVar(value=item["requester"])
            ctk.CTkCheckBox(foot, text="One person may fill more than one sign-off", variable=same,
                            command=lambda: item.update(same=bool(same.get()))).grid(row=1, column=0, sticky="w",
                                                                                     pady=(8, 0))
            ctk.CTkCheckBox(foot, text="The person who asks may be a signer", variable=req,
                            command=lambda: item.update(requester=bool(req.get()))).grid(row=2, column=0,
                                                                                         sticky="w", pady=(6, 0))
            eco = tk.BooleanVar(value=item["eco"])
            ctk.CTkCheckBox(foot, text="Require ECO (an engineering change order is filled in when it starts)",
                            variable=eco, command=lambda: item.update(eco=bool(eco.get()))).grid(
                row=3, column=0, sticky="w", pady=(6, 0))

    def _draw_row(self, holder, action, index, number, roles):
        line = ctk.CTkFrame(holder, fg_color="transparent")
        line.grid(row=number, column=0, sticky="w", pady=(6 if number == 0 else 3, 0), padx=6)
        ctk.CTkLabel(line, text=f"Sign-off {number + 1}", width=80, anchor="w", text_color=theme.MUTED).grid(
            row=0, column=0, padx=(0, 6))
        column = 1
        for position, role in enumerate(roles):
            if position:
                ctk.CTkLabel(line, text="or", text_color=theme.MUTED).grid(row=0, column=column, padx=4)
                column += 1
            var = tk.StringVar(value=role)
            ctk.CTkOptionMenu(line, variable=var, values=self.roles or [role], width=170, height=30, fg_color=theme.GRAY,
                              button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                              command=lambda value, a=action, i=index, n=number, p=position:
                              self.editor.set_role(a, i, n, p, value)).grid(row=0, column=column)
            column += 1
            if len(roles) > 1:
                release_button.ReleaseButton(line, text="x", width=26, height=26, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                              command=lambda a=action, i=index, n=number, p=position: self._remove_or(a, i, n, p)
                              ).grid(row=0, column=column, padx=(2, 0))
                column += 1
        release_button.ReleaseButton(line, text="+ or", width=50, height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=lambda: self._add_or(action, index, number)).grid(row=0, column=column, padx=(8, 4))
        release_button.ReleaseButton(line, text="Remove", width=76, height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=lambda: self._remove_row(action, index, number)).grid(row=0, column=column + 1)

    # -- changes -----------------------------------------------------------
    def _select(self, action, name):
        self.selected[action] = self.editor.names(action).index(name)
        self._redraw(action)

    def _new(self, action):
        if not self.roles:
            self.problem.configure(text="This org has no roles yet. Add some in Team > Roles... first.")
            return
        self.selected[action] = self.editor.add(action, self.roles)
        self._redraw(action)

    def _delete(self, action):
        names = self.editor.names(action)
        index = self.selected[action]
        if names and messagebox.askyesno("Delete workflow", f"Delete the {workflow_templates.label_of(action)} workflow "
                                         f"'{names[index]}'? Requests already waiting keep their sign-offs.",
                                         parent=self):
            self.editor.delete(action, index)
            self._redraw(action)

    def _rename(self, action, text):
        index = self.selected[action]
        if index < len(self.editor.items[action]):
            self.editor.items[action][index]["name"] = text

    def _add_row(self, action, index):
        self.editor.add_row(action, index, self.roles)
        self._redraw(action)

    def _remove_row(self, action, index, number):
        self.editor.remove_row(action, index, number)
        self._redraw(action)

    def _add_or(self, action, index, number):
        if self.editor.add_or(action, index, number, self.roles) is None:
            self.problem.configure(text="Every role is already listed on that sign-off.")
            return
        self._redraw(action)

    def _remove_or(self, action, index, number, position):
        self.editor.remove_or(action, index, number, position)
        self._redraw(action)

    def _standard(self):
        added, skipped = self.editor.add_standard(self.roles)
        for action in workflow_templates.ACTIONS:
            self._redraw(action)
        lines = []
        if added:
            lines.append("Added: " + ", ".join(added) + ".")
        if skipped:
            lines.append("Not added because the org lacks these roles (add them in Team > Roles... first): "
                         + "; ".join(f"{name} needs {', '.join(missing)}" for name, missing in skipped) + ".")
        if not lines:
            lines.append("The standard workflows are all there already.")
        messagebox.showinfo("Standard workflows", "\n\n".join(lines), parent=self)

    def _save(self):
        if not self.editor.dirty:
            self.destroy()
            return
        problem = self.editor.problem()
        if problem:
            self.problem.configure(text=problem)
            return
        ops = self.editor.ops()
        if self.apply is not None:
            problem = self.apply(ops, self.editor)
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = ops
        self.destroy()
