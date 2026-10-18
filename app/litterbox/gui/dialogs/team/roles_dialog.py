"""
roles_dialog.py - the team's list of roles.
"""

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
    """The list of roles this org uses. Type a role and press Add; select one and press Remove.

        RolesDialog(parent, roles, holders_of).show()      # holders_of(role) -> names of people who have it
        # None if cancelled, else the new list of roles. Nothing is saved until the caller saves it.
    """
    FOCUS = "entry"

    def __init__(self, parent, roles, holders_of, apply=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.apply = apply          # apply(roles) -> problem text, or "" when the change was taken
        self.roles = list(roles)
        self.initial = list(roles)
        self.holders_of = holders_of
        width, height = 460, 560
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Roles")
        self.geometry(f"{width}x{height}+{x}+{y}")
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
        self.tree = ttk.Treeview(frame, columns=("role",), show="headings", selectmode="browse")
        self.tree.heading("role", text="Role", anchor="w")
        self.tree.column("role", anchor="w")
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
        release_button.ReleaseButton(self, text="Add the standard roles", height=30, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._standard).grid(row=3, column=0, sticky="w", padx=20, pady=(8, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="OK", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self._show()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _cancel(self):
        if self.roles != self.initial and not confirm_dialogs.ask_discard(self, "your changes to the roles"):
            return
        self.destroy()

    def _show(self):
        self.tree.delete(*self.tree.get_children())
        for role in self.roles:
            self.tree.insert("", "end", iid=role, values=(role,))

    def _add(self):
        problem, role = team_text.add_role_result(self.entry.get(), self.roles)
        self.problem.configure(text=problem)
        if problem:
            return
        self.roles.append(role)
        self.entry.delete(0, "end")
        self._show()

    def _remove(self):
        chosen = self.tree.selection()
        if not chosen:
            self.problem.configure(text="Select a role to remove.")
            return
        role = chosen[0]
        if not messagebox.askyesno("Remove role", team_text.role_removal_text(role, self.holders_of(role)), parent=self):
            return
        self.roles.remove(role)
        self.problem.configure(text="")
        self._show()

    def _standard(self):
        for role in team_model.STANDARD_ROLES:
            if role.lower() not in (r.lower() for r in self.roles):
                self.roles.append(role)
        self._show()

    def _save(self):
        if self.roles == self.initial:                  # nothing changed: nothing to keep
            self.destroy()
            return
        if self.apply is not None:
            problem = self.apply(list(self.roles))
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = list(self.roles)
        self.destroy()
