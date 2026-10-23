"""
roles_dialog.py - the team's list of roles, and which are superuser roles (whoever holds one may sign for anyone).
"""

import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.logic import team_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.team import team_model


class RolesDialog(modal_dialog.ModalDialog):
    """The list of roles this org uses. Type a role and press Add; select one and press Remove. The Superuser box
    says whether the selected role may sign for anyone.

        RolesDialog(parent, roles, holders_of, superusers=["Chief"]).show()     # holders_of(role) -> names
        # None if cancelled, else (roles, superuser roles). Nothing is saved until the caller saves it.
    """
    FOCUS = "entry"

    def __init__(self, parent, roles, holders_of, apply=None, superusers=()):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.apply = apply          # apply(roles, superusers) -> problem text, or "" when the change was taken
        self.roles = list(roles)
        self.initial = list(roles)
        self.superusers = [r for r in self.roles if r.lower() in {s.lower() for s in superusers}]
        self.initial_superusers = list(self.superusers)
        self.holders_of = holders_of
        width, height = 460, 600
        self.title("Roles")
        window_chrome.place_over(self, parent, width, height)
        self.minsize(380, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Roles this org uses", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("role", "superuser"), show="headings", selectmode="browse")
        self.tree.heading("role", text="Role", anchor="w")
        self.tree.heading("superuser", text="Superuser", anchor="w")
        self.tree.column("role", anchor="w")
        self.tree.column("superuser", width=90, stretch=False, anchor="w")
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._selected())
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        add_row = ctk.CTkFrame(self, fg_color="transparent")
        add_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        add_row.columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(add_row, height=34, placeholder_text="New role, for example Reviewer")
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry.bind("<Return>", lambda event: self._add())
        release_button.ReleaseButton(add_row, text="Add", width=80, fg_color=theme.ACCENT, hover_color="#18527f",
                      command=self._add).grid(row=0, column=1, padx=(0, 6))
        release_button.ReleaseButton(add_row, text="Remove", width=80, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._remove).grid(row=0, column=2)
        self.superuser_var = tk.BooleanVar(value=False)
        self.superuser_box = ctk.CTkCheckBox(self, text="Superuser (this role can sign for anyone)",
                                             variable=self.superuser_var, command=self._superuser_ticked,
                                             state="disabled")
        self.superuser_box.grid(row=3, column=0, sticky="w", padx=20, pady=(10, 0))
        release_button.ReleaseButton(self, text="Add the standard roles", height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._standard).grid(row=4, column=0, sticky="w", padx=20, pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="OK", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._show()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _changed(self):
        return self.roles != self.initial or self.superusers != self.initial_superusers

    def _cancel(self):
        if self._changed() and not confirm_dialogs.ask_discard(self, "your changes to the roles"):
            return
        self.destroy()

    def _show(self, select=None):
        keep = select or next(iter(self.tree.selection()), None)
        self.tree.delete(*self.tree.get_children())
        for role in self.roles:
            self.tree.insert("", "end", iid=role, values=(role, "Yes" if role in self.superusers else ""))
        if keep in self.roles:
            self.tree.selection_set(keep)
        self._selected()

    def _selected(self):
        """The Superuser box shows (and changes) the selected role; with nothing selected it is greyed out."""
        chosen = self.tree.selection()
        role = chosen[0] if chosen else None
        self.superuser_var.set(role in self.superusers)
        self.superuser_box.configure(state="normal" if role else "disabled")

    def _superuser_ticked(self):
        chosen = self.tree.selection()
        if not chosen:
            return
        role = chosen[0]
        if self.superuser_var.get() and role not in self.superusers:
            self.superusers = [r for r in self.roles if r in self.superusers or r == role]
        elif not self.superuser_var.get() and role in self.superusers:
            self.superusers.remove(role)
        self._show(role)

    def _add(self):
        problem, role = team_text.add_role_result(self.entry.get(), self.roles)
        self.problem.configure(text=problem)
        if problem:
            return
        self.roles.append(role)
        self.entry.delete(0, "end")
        self._show(role)                                # selected, so the Superuser box is for the new role

    def _remove(self):
        chosen = self.tree.selection()
        if not chosen:
            self.problem.configure(text="Select a role to remove.")
            return
        role = chosen[0]
        if not messagebox.askyesno("Remove role", team_text.role_removal_text(role, self.holders_of(role)), parent=self):
            return
        self.roles.remove(role)
        if role in self.superusers:
            self.superusers.remove(role)
        self.problem.configure(text="")
        self._show()

    def _standard(self):
        """Add the standard roles that are missing. A standard superuser role (Chief) comes in ticked."""
        standard = {r.lower() for r in team_model.STANDARD_SUPERUSER_ROLES}
        for role in team_model.STANDARD_ROLES:
            if role.lower() not in (r.lower() for r in self.roles):
                self.roles.append(role)
                if role.lower() in standard:
                    self.superusers.append(role)
        self.superusers = [r for r in self.roles if r in self.superusers]
        self._show()

    def _save(self):
        if not self._changed():                         # nothing changed: nothing to keep
            self.destroy()
            return
        if self.apply is not None:
            problem = self.apply(list(self.roles), list(self.superusers))
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = (list(self.roles), list(self.superusers))
        self.destroy()
