"""
team_screen.py - the Team screen: people, roles, workflows and vault settings (changes are drafted, then saved
once). A screen of the main window, chosen in the sidebar; unsaved changes stay while you look at other screens.

    +---------------------------------------------------------------------------------+
    | Team                                          | 2 unsaved changes  Discard  Save | (only while there are some)
    | You: Austin (Owner)   [Who am I?] [Signing...]                                   |
    | +- People -------------------------------------------+  +- Organization -----+ |
    | | [Add Person] [Edit] [Switch On/Off] [More v]       |  | Roles...           | |
    | | Name  Email  Access  Roles  On                     |  | Workflows...       | |
    | | ...                                                |  | Projects...        | |
    | | the highlighted person's host names, keys and roles|  | Vault Settings...  | |
    | +----------------------------------------------------+  +--------------------+ |
    | what just happened                                                              |
    +---------------------------------------------------------------------------------+

Buttons you may not use are greyed out (never hidden), with a tooltip saying why.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.dialogs.team import signing_dialog
from litterbox.gui.logic import team_text
from litterbox.gui.widgets import menu_bar
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.gui.widgets import tooltip
from litterbox.team import team_identity
from litterbox.team import team_store
from litterbox.team.draft import TeamDraft
from litterbox.workflows import workflow_store


COLUMNS = (("name", "Name", 170), ("email", "Email", 210), ("access", "Access", 80), ("roles", "Roles", 240),
           ("active", "On", 40))

NO_TEAM = "This vault has no team list yet, so everyone can do everything. Setting one up makes you the Owner; " \
          "then only people you add can change anything."


class TeamScreen(ctk.CTkFrame):
    """The team list: who may do what. Everyone can look; Admins and the Owner can change it."""

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.busy = False
        self.draft = None               # your unsaved changes (team_draft.TeamDraft); None until the team exists
        self.directory = None           # the team list as shown (the draft's, when there is one)
        self.actions = []               # (button, why_not() -> "" when it may be pressed)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_header()
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=16)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_people(body)
        self._build_organization(body)
        self.status = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=900)
        self.status.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 12))
        self.reload()

    # -- building ------------------------------------------------------------------------------------------------
    def _action(self, parent, text, command, why_not, color=theme.GRAY, hover=theme.GRAY_HOVER, width=120):
        """A button that greys itself out (with why_not() as its tooltip) whenever why_not() says so."""
        button = release_button.ReleaseButton(parent, text=text, width=width, fg_color=color, hover_color=hover,
                                              command=command)
        self.actions.append((button, why_not))
        tooltip.Tooltip(button, lambda: why_not() if button.cget("state") == "disabled" else "")
        return button

    @staticmethod
    def _card(parent, title):
        card = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=10)
        card.columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=14, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        return card

    def _build_header(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        top.columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Team", font=ctk.CTkFont(size=18, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w")
        self.unsaved = ctk.CTkFrame(top, fg_color=theme.BG_PANEL, corner_radius=8)
        self.unsaved.grid(row=0, column=1, rowspan=2, sticky="e")
        self.unsaved_label = ctk.CTkLabel(self.unsaved, text="", text_color=theme.WARN, anchor="e")
        self.unsaved_label.grid(row=0, column=0, padx=(12, 10), pady=6)
        tooltip.Tooltip(self.unsaved_label, lambda: self.draft.summary() if self.draft is not None else "")
        self._action(self.unsaved, "Discard", self.discard, self._busy, width=90).grid(row=0, column=1, padx=(0, 6))
        self.save_button = self._action(self.unsaved, "Save", lambda: self.app.save_team(self), self._busy,
                                        theme.GREEN, theme.GREEN_HOVER, 90)
        self.save_button.grid(row=0, column=2, padx=(0, 6), pady=6)
        you = ctk.CTkFrame(top, fg_color="transparent")
        you.grid(row=1, column=0, sticky="w", pady=(2, 8))
        self.summary = ctk.CTkLabel(you, text="", anchor="w", justify="left")
        self.summary.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._action(you, "Who am I?", self.app.who_am_i, self._busy, width=100).grid(row=0, column=1, padx=(0, 6))
        self._action(you, "Signing...", lambda: signing_dialog.SigningDialog(self.app, self.app.repo()),
                     self._busy, width=100).grid(row=0, column=2)

    def _build_people(self, parent):
        card = self._card(parent, "People")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        card.rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.set_up_button = self._action(bar, "Set Up Team", self.app.set_up_team, self._busy, theme.ACCENT,
                                          "#18527f", 130)
        self.set_up_button.grid(row=0, column=0, padx=(0, 6))
        self.people_buttons = [
            self._action(bar, "Add Person", lambda: self.app.edit_person(self, None, adding=True),
                         lambda: self._why_not("manage_people")),
            self._action(bar, "Edit", lambda: self.app.edit_person(self, self._selected()),
                         lambda: self._why_not("manage_people", needs_person=True), width=90),
            self._action(bar, "Switch On/Off", lambda: self.app.toggle_person(self, self._selected()),
                         lambda: self._why_not("manage_people", needs_person=True))]
        for column, button in enumerate(self.people_buttons, start=1):
            button.grid(row=0, column=column, padx=(0, 6))
        self.more_button = menu_bar.DropButton(bar, "More", self._fill_more, width=90, fg_color=theme.GRAY,
                                               hover_color=theme.GRAY_HOVER)
        self.more_button.grid(row=0, column=len(self.people_buttons) + 1)
        table = ctk.CTkFrame(card, fg_color="transparent")
        table.grid(row=2, column=0, sticky="nsew", padx=(8, 4))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for name, _title, width in COLUMNS:
            self.tree.column(name, width=width, anchor="w")
        table_sorting.TableSorter(self.tree, [(c[0], c[1]) for c in COLUMNS])
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(table, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._selection_changed(), add="+")
        self.tree.bind("<Double-1>", self._on_double_click, add="+")
        self.person_details = ctk.CTkLabel(card, text="", text_color=theme.MUTED, anchor="w", justify="left",
                                           wraplength=700)
        self.person_details.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 10))
        card.bind("<Configure>", lambda event: self._wrap_details(event.width), add="+")

    def _build_organization(self, parent):
        card = self._card(parent, "Organization")
        card.grid(row=0, column=1, sticky="nsew")
        entries = (("Roles...", lambda: self.app.edit_roles(self), lambda: self._why_not("manage_people")),
                   ("Workflows...", lambda: self.app.edit_workflow(self), lambda: self._why_not("manage_workflows")),
                   ("Projects...", lambda: self.app.manage_projects(self), lambda: self._why_not("manage_settings", team=False)),
                   ("Document Types...", lambda: self.app.manage_doc_types(self),
                    lambda: self._why_not("manage_doc_types", team=False)),
                   ("Vault Settings...", lambda: self.app.edit_vault_settings(self),
                    lambda: self._why_not("manage_settings", team=False)))
        for row, (text, command, why_not) in enumerate(entries, start=1):
            self._action(card, text, command, why_not, width=170).grid(row=row, column=0, sticky="ew", padx=12,
                                                                       pady=(0, 6))

    def _fill_more(self, menu):
        why = self._why_not("transfer_owner", needs_person=True)
        menu.add_command(label="Transfer Ownership...", state="disabled" if why else "normal",
                         command=lambda: self.app.transfer_owner(self, self._selected()))
        if why:
            menu.add_command(label=f"    ({why})", state="disabled")

    # -- state ---------------------------------------------------------------------------------------------------
    def _busy(self):
        return "Wait for the change that is running to finish." if self.busy else ""

    def _why_not(self, action, needs_person=False, team=True):
        """'' if the button may be pressed now, else why not (for its tooltip). team: it needs the team list."""
        if self.busy:
            return self._busy()
        if team and self.draft is None:
            return "Set up the team first."
        allowed, why = self.app.identity.allows(action)
        if not allowed:
            return why
        if needs_person and self._selected() is None:
            return "Select a person in the list first."
        return ""

    def _update_buttons(self):
        for button, why_not in self.actions:
            button.configure(state="disabled" if why_not() else "normal")
        if self.draft is not None and self.draft.dirty:
            count = len(self.draft.labels)
            self.unsaved_label.configure(text=f"{count} unsaved change{'s' if count != 1 else ''}")
            self.unsaved.grid()
        else:
            self.unsaved.grid_remove()
        no_team = self.directory is None
        for button in self.people_buttons + [self.more_button]:
            if no_team:
                button.grid_remove()
            else:
                button.grid()
        if no_team:
            self.set_up_button.grid()
        else:
            self.set_up_button.grid_remove()
        self.more_button.configure(state="disabled" if self.busy or no_team else "normal")

    def _selection_changed(self):
        self._update_buttons()
        person = self.directory.get(self._selected()) if self.directory is not None and self._selected() else None
        self.person_details.configure(text=team_text.person_details(person) if person is not None else
                                      ("" if self.directory is None else "Click a person to see their details."))

    def _wrap_details(self, width):
        scale = getattr(self.app, "scale", 1.0) or 1.0
        self.person_details.configure(wraplength=max(width / scale - 30, 200))

    def _on_double_click(self, event):
        if self.tree.identify_row(event.y) and not self._why_not("manage_people", needs_person=True):
            self.app.edit_person(self, self._selected())

    def say(self, text, tone="normal"):
        """Show what Litterbox is doing, so you can see a click did something."""
        self.status.configure(text=text, text_color={"normal": theme.MUTED, "warn": theme.WARN, "error": theme.ERROR}.get(tone, theme.MUTED))

    def set_busy(self, busy):
        self.busy = busy
        if not busy:
            self.reload()                        # also puts the Save button back to the right state
            return
        self._update_buttons()

    def may_leave(self):
        """Before the org changes: True if there are no unsaved changes, or the person agrees to lose them."""
        if self.draft is not None and self.draft.dirty and not confirm_dialogs.ask_discard(
                self.winfo_toplevel(), "all the unsaved team changes"):
            return False
        self.draft = None
        return True

    def discard(self):
        """Throw away the unsaved changes (after asking) and show the vault's team list as it is."""
        if self.draft is None or not self.draft.dirty:
            return
        if confirm_dialogs.ask_discard(self.winfo_toplevel(), "all the unsaved team changes"):
            self.draft = None
            self.reload()
            self.say("Discarded the unsaved team changes.")

    def _new_draft(self):
        identity = self.app.identity
        if identity.state == team_identity.LEGACY or identity.directory is None:
            return None
        try:
            templates = workflow_store.load(self.app.repo())
        except LitterboxError:
            templates = {}
        return TeamDraft(identity.directory, templates, identity.person.id if identity.person else "")

    def reload(self):
        """Redraw from the vault's team file (or your unsaved changes) and the current identity."""
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
        self.directory = directory
        if directory is None:
            self.summary.configure(text=NO_TEAM, wraplength=700)
        else:
            for iid, values in team_text.people_table(directory):
                self.tree.insert("", "end", iid=iid, values=values[:len(COLUMNS)])
            self.summary.configure(text=f"You: {identity.describe()}.", wraplength=0)
        for iid in keep:                                    # keep the same person selected after a change
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
        self._selection_changed()

    def _selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None
