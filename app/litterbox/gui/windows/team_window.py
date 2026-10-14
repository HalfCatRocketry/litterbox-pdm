"""
team_window.py - the Team window: people, roles, workflows and vault settings (changes are drafted,
then saved once).
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.dialogs.team import signing_dialog
from litterbox.gui.logic import team_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.team import team_identity
from litterbox.team import team_store
from litterbox.team.draft import TeamDraft
from litterbox.workflows import workflow_store


class TeamWindow(ctk.CTkToplevel):
    """The team list: who may do what. Everyone can look; Admins and the Owner can change it."""

    def __init__(self, app):
        super().__init__(app)
        window_chrome.set_window_icon(self)
        self.app = app
        self.title("Team")
        self.geometry("1000x560")
        self.minsize(760, 420)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.summary = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=940)
        self.summary.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = (("name", "Name", 170), ("email", "Email", 190), ("access", "Access", 70), ("roles", "Roles", 200),
                   ("active", "On", 40), ("hosts", "Host names", 200), ("keys", "Keys", 50))
        self.tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for name, _title, width in columns:
            self.tree.column(name, width=width, anchor="w")
        table_sorting.TableSorter(self.tree, [(c[0], c[1]) for c in columns])
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.buttons = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 4))
        self.status = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=940)
        self.status.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.busy = False
        self.draft = None               # your unsaved changes (team_draft.TeamDraft); None until the team exists
        self.save_button = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda event: self.close())
        self.reload()
        self.after(100, self.lift)

    BUTTONS_PER_ROW = 5                 # more than this and the buttons start a new row instead of running off

    def _button(self, text, command, color=theme.GRAY, hover=theme.GRAY_HOVER, width=130):
        button = release_button.ReleaseButton(self.buttons, text=text, width=width, fg_color=color, hover_color=hover,
                               command=command)
        index = len(self.buttons.winfo_children()) - 1
        button.grid(row=index // self.BUTTONS_PER_ROW, column=index % self.BUTTONS_PER_ROW, padx=(0, 6),
                    pady=(0, 6), sticky="w")
        return button

    def close(self):
        """Close the window; if there are unsaved changes, ask first."""
        if self.draft is not None and self.draft.dirty and not confirm_dialogs.ask_discard(self, "all the unsaved team changes"):
            return
        self.destroy()

    def _new_draft(self):
        identity = self.app.identity
        if identity.state == team_identity.LEGACY or identity.directory is None:
            return None
        try:
            templates = workflow_store.load(self.app.repo())
        except LitterboxError:
            templates = {}
        return TeamDraft(identity.directory, templates, identity.person.id if identity.person else "")

    def say(self, text, tone="normal"):
        """Show what Litterbox is doing, so you can see a click did something."""
        self.status.configure(text=text, text_color={"normal": theme.MUTED, "warn": theme.WARN, "error": theme.ERROR}.get(tone, theme.MUTED))

    def set_busy(self, busy):
        self.busy = busy
        if not busy:
            self.reload()                        # also puts the Save button back to the right state
            return
        for button in self.buttons.winfo_children():
            button.configure(state="disabled")

    def reload(self):
        """Redraw from the vault's team file and the current identity."""
        for child in self.buttons.winfo_children():
            child.destroy()
        identity = self.app.identity
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        if self.draft is None or not self.draft.dirty:      # nothing unsaved: show the vault as it is now
            self.draft = self._new_draft()
        directory = self.draft.directory if self.draft is not None else identity.directory
        if identity.state == team_identity.LEGACY:
            directory = None
        elif directory is None:
            try:
                directory = team_store.load(self.app.repo())
            except LitterboxError:
                directory = None
        self.save_button = None
        if directory is None:
            self.summary.configure(text="This vault has no team list yet, so everyone can do everything. Setting "
                                        "one up makes you the Owner; then only people you add can change anything.")
            self._button("Set Up Team", self.app.set_up_team, theme.ACCENT, "#18527f")
        else:
            for iid, values in team_text.people_table(directory):
                self.tree.insert("", "end", iid=iid, values=values)
            unsaved = self.draft.summary() if self.draft is not None else ""
            self.summary.configure(text=f"You: {identity.describe()}."
                                        + (f"\n{unsaved}. Press Save to upload them." if unsaved else ""))
            if identity.allows("manage_people")[0]:
                self._button("Add Person", lambda: self.app.edit_person(self, None, adding=True))
                self._button("Edit", lambda: self.app.edit_person(self, self._selected()))
                self._button("Switch On/Off", lambda: self.app.toggle_person(self, self._selected()))
                self._button("Roles...", lambda: self.app.edit_roles(self))
            if identity.allows("manage_workflows")[0]:
                self._button("Workflows...", lambda: self.app.edit_workflow(self), theme.PURPLE, theme.PURPLE_HOVER)
            if identity.allows("transfer_owner")[0]:
                self._button("Transfer Ownership", lambda: self.app.transfer_owner(self, self._selected()), theme.PURPLE,
                             theme.PURPLE_HOVER, 150)
        if identity.allows("manage_settings")[0]:
            self._button("Vault Settings...", lambda: self.app.edit_vault_settings(self), theme.PURPLE, theme.PURPLE_HOVER, 140)
        self._button("Who am I?", self.app.who_am_i)
        self._button("Signing...", lambda: signing_dialog.SigningDialog(self.app, self.app.repo()))
        if self.draft is not None and (identity.allows("manage_people")[0] or identity.allows("manage_workflows")[0]):
            self.save_button = self._button("Save", lambda: self.app.save_team(self), theme.GREEN, theme.GREEN_HOVER, 100)
            self.save_button.configure(state="normal" if self.draft.dirty and not self.busy else "disabled")
        self._button("Close", self.close)
        for iid in keep:                                    # keep the same person selected after a change
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        if self.busy:
            for button in self.buttons.winfo_children():
                button.configure(state="disabled")

    def _selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None
