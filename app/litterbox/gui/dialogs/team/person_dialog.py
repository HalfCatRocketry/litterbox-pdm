"""
person_dialog.py - adding or changing one person on the team.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.logic import team_text
from litterbox.gui.widgets import release_button


class PersonDialog(ctk.CTkToplevel):
    """Add or edit one person on the team.

        PersonDialog(parent, person_or_None, roles, existing_ids, can_set_access, host_name_hint).show()
        # None if cancelled, else (problem-free) dict of fields; for a new person it includes 'id'
    """

    ADD_ROLE = "Add a role..."

    def __init__(self, parent, person, roles, existing_ids, can_set_access, host_name_hint="", apply=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.apply = apply          # apply(fields) -> problem text, or "" when the change was taken
        self.person, self.existing_ids = person, existing_ids
        width, height = 520, 700
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Add Person" if person is None else f"Edit {person.name}")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        def label(row, text):
            ctk.CTkLabel(self, text=text, anchor="w", text_color=theme.MUTED).grid(
                row=row, column=0, sticky="ew", padx=20, pady=(8, 0))

        def entry(row, value=""):
            box = ctk.CTkEntry(self, height=32)
            box.grid(row=row, column=1 - 1, sticky="ew", padx=20)
            box.insert(0, value)
            return box

        label(0, "Name (required)")
        self.name_entry = entry(1, person.name if person else "")
        label(2, "Email")
        self.email_entry = entry(3, person.email if person else "")
        label(4, "Names the host may report for this person (commas between). Use Who am I? on their computer.")
        self.host_entry = entry(5, ", ".join(person.host_names) if person else host_name_hint)
        label(6, "Access")
        self.access_var = tk.StringVar(value=(person.access if person else "member").capitalize())
        self.access_menu = ctk.CTkOptionMenu(self, variable=self.access_var, values=["Member", "Admin"], width=140,
                                             fg_color=theme.GRAY, button_color=theme.GRAY_HOVER)
        self.access_menu.grid(row=7, column=0, sticky="w", padx=20)
        if person is not None and person.access == "owner":
            self.access_var.set("Owner")
            self.access_menu.configure(state="disabled")
        elif not can_set_access:
            self.access_menu.configure(state="disabled")
        label(8, "Roles: pick from the list to add; select one in the box and press Remove to take it off")
        self.all_roles = list(roles)
        self.chosen_roles = list(person.roles) if person else []
        roles_row = ctk.CTkFrame(self, fg_color="transparent")
        roles_row.grid(row=9, column=0, sticky="ew", padx=20)
        roles_row.columnconfigure(1, weight=1)
        pick_box = ctk.CTkFrame(roles_row, fg_color="transparent")
        pick_box.grid(row=0, column=0, sticky="n")
        self.role_var = tk.StringVar(value=self.ADD_ROLE)
        self.role_menu = ctk.CTkOptionMenu(pick_box, variable=self.role_var, values=[self.ADD_ROLE], width=200,
                                           fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, command=self._role_picked)
        self.role_menu.grid(row=0, column=0)
        release_button.ReleaseButton(pick_box, text="Remove", width=200, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._remove_role).grid(row=1, column=0, pady=(6, 0))
        self.role_tree = ttk.Treeview(roles_row, columns=("role",), show="headings", height=4, selectmode="browse")
        self.role_tree.heading("role", text="This person's roles", anchor="w")
        self.role_tree.column("role", width=240, anchor="w")
        self.role_tree.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self._show_roles()
        label(10, "Signing keys (optional): one public key per line, given to you by the person")
        self.keys_box = ctk.CTkTextbox(self, height=90, fg_color=theme.BG_PANEL)
        self.keys_box.grid(row=11, column=0, sticky="ew", padx=20)
        if person:
            self.keys_box.insert("1.0", "\n".join(person.signing_keys))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left", wraplength=470)
        self.problem.grid(row=12, column=0, sticky="ew", padx=20, pady=(8, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=13, column=0, sticky="ew", padx=20, pady=(8, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="OK", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.initial = self._snapshot()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)

    def _snapshot(self):
        return (self.name_entry.get(), self.email_entry.get(), self.host_entry.get(), self.access_var.get(),
                tuple(self.chosen_roles), self.keys_box.get("1.0", "end").strip())

    def _cancel(self):
        if self._snapshot() != self.initial and not confirm_dialogs.ask_discard(self, "your changes to this person"):
            return
        self.destroy()

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.name_entry.focus_set()
        except tk.TclError:
            pass

    def _show_roles(self):
        self.role_tree.delete(*self.role_tree.get_children())
        for role in self.chosen_roles:
            self.role_tree.insert("", "end", iid=role, values=(role,))
        left = team_text.roles_to_choose(self.all_roles, self.chosen_roles)
        self.role_menu.configure(values=[self.ADD_ROLE] + left)
        self.role_var.set(self.ADD_ROLE)

    def _role_picked(self, choice):
        if choice != self.ADD_ROLE and choice not in self.chosen_roles:
            self.chosen_roles.append(choice)
        self._show_roles()

    def _remove_role(self):
        chosen = self.role_tree.selection()
        if chosen and chosen[0] in self.chosen_roles:
            self.chosen_roles.remove(chosen[0])
        self._show_roles()

    def _save(self):
        form = {"name": self.name_entry.get(), "email": self.email_entry.get(), "host_names": self.host_entry.get(),
                "roles": ", ".join(self.chosen_roles), "keys": self.keys_box.get("1.0", "end"),
                "access": self.access_var.get()}
        problem, fields = team_text.person_form_result(None if self.person is None else self.person.id, form,
                                                   self.existing_ids)
        self.problem.configure(text=problem)
        if problem:
            return
        if self.apply is not None:
            problem = self.apply(dict(fields))
            self.problem.configure(text=problem)
            if problem:
                return
        self.result = fields
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result
