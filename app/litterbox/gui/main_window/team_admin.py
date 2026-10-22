"""
team_admin.py - what the Team screen's buttons do: who am I, setting up the team, people, roles,
handing over the Owner role, vault settings, projects, workflows, and saving the draft.
"""

from tkinter import messagebox

from litterbox.cad import solidworks_versions
from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui.dialogs import projects_dialog
from litterbox.gui.dialogs import vault_settings_dialog
from litterbox.gui.dialogs.team import person_dialog
from litterbox.gui.dialogs.team import roles_dialog
from litterbox.gui.dialogs.workflow import workflows_dialog
from litterbox.gui.logic import error_text
from litterbox.gui.logic import project_text
from litterbox.gui.logic import team_text
from litterbox.gui.logic import workflow_editor
from litterbox.gui.widgets import release_button
from litterbox.team import team_editing
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.vault import config
from litterbox.vault import project_admin
from litterbox.vault import settings_admin as vault_settings
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_templates


class TeamAdmin:
    """what the Team screen's buttons do: who am I, setting up the team, people, roles, (a part of the main window, App)."""

    def _team_windows(self):
        """The Team screen, once it has been opened (a list, so callers can loop over it)."""
        screen = getattr(self, "screens", {}).get("team")
        return [screen] if screen is not None else []

    def _show_identity(self):
        text, tone = team_text.identity_banner(self.identity)
        self.identity_label.configure(text=text, text_color=theme.WARN if tone == "warn" else theme.MUTED)
        self._refresh_tasks()

    def show_team(self):
        release_button.click_log("opening the Team screen")
        self.show_screen("team")

    def who_am_i(self):
        repo = self.repo()
        parent = self._popup_parent()

        def show(who):
            self.identity = who
            self._show_identity()
            messagebox.showinfo("Who am I?", team_text.who_am_i_text(who) if who.state != team_identity.UNVERIFIED
                                else who.message(), parent=parent)

        self.run_task(lambda: team_identity.current(repo, refresh=True), "Checked who you are", on_success=show,
                      refresh=False)

    def set_up_team(self):
        if not messagebox.askokcancel(
                "Set up the team",
                "This creates the team list for this vault and makes YOU its Owner.\n\nFrom then on, only people an "
                "Admin adds to the list can change anything; everyone else can look and open files.\n\n"
                "Litterbox needs the internet to ask the host who you are."):
            return
        repo = self.repo()
        self.run_task(lambda: (team_setup.setup_team(repo), team_identity.current(repo, refresh=True))[1], "The team is set up",
                      on_success=self._team_changed)

    def _team_changed(self, who):
        self.identity = who
        self._show_identity()
        for screen in self._team_windows():
            screen.reload()

    def _stage(self, window, label, change, needs_owner=False):
        """Add a change to the Team screen's unsaved changes. Returns "" if it was taken, else why not."""
        draft = window.draft
        if draft is None:
            return "The team isn't set up yet."
        try:
            draft.stage_people(label, change, needs_owner)
        except LitterboxError as e:
            return error_text.shorten(str(e))
        window.reload()
        return ""

    def edit_person(self, window, person_id, adding=False):
        if not self._may("manage_people"):
            return
        directory = window.draft.directory if window.draft is not None else self.identity.directory
        person = None if adding else (directory.get(person_id) if person_id else None)
        if person is None and not adding:
            self._say("Select a person first.", "warn")
            return

        def apply(fields):
            if person is None:
                new_id = fields.pop("id")
                return self._stage(window, f"Add {fields['name']}",
                                   lambda d, who: team_editing.add_person(d, who, new_id, **fields))
            if team_text.person_unchanged(person, fields):
                return ""
            pid = person.id
            return self._stage(window, f"Edit {person.name}", lambda d, who: team_editing.update_person(d, who, pid, **fields))

        person_dialog.PersonDialog(window, person, directory.roles, [p.id for p in directory.people],
                     self.identity.access == team_model.OWNER, apply=apply).show()

    def toggle_person(self, window, person_id):
        if not self._may("manage_people"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select a person first.", "warn")
            return
        turn_on, pid = not person.active, person.id
        problem = self._stage(window, f"Switch {'on' if turn_on else 'off'} {person.name}",
                              lambda d, who: team_editing.set_active(d, who, pid, turn_on))
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_roles(self, window):
        if not self._may("manage_people") or window.draft is None:
            return
        directory = window.draft.directory
        roles_dialog.RolesDialog(window, directory.roles, lambda role: team_editing.holders_of(window.draft.directory, role),
                    apply=lambda roles, superusers: self._stage(window, "Roles", lambda d, who: team_editing.set_roles(
                        d, who, roles, scrub=True, superusers=superusers)),
                    superusers=directory.superuser_roles).show()

    def transfer_owner(self, window, person_id):
        if not self._may("transfer_owner"):
            return
        person = window.draft.directory.get(person_id) if person_id and window.draft is not None else None
        if person is None:
            self._say("Select the person who will become the Owner.", "warn")
            return
        if not messagebox.askokcancel(
                "Transfer ownership",
                f"Make {person.name} the Owner? You will become an Admin, and only {person.name} will be able to "
                "hand ownership on again.\n\nThis takes effect when you press Save.", parent=window):
            return
        pid = person.id
        problem = self._stage(window, f"{person.name} becomes the Owner",
                              lambda d, who: team_editing.transfer_owner(d, who, pid), needs_owner=True)
        if problem:
            messagebox.showwarning("Team", problem, parent=window)

    def edit_vault_settings(self, window):
        if not self._may("manage_settings"):
            return
        repo = self.repo()
        try:
            config.apply(repo)
            current = {"org_name": config.check_org_name(config.load(repo).get("org_name")),
                       "commit_style": config.get_commit_style(repo), "release_rule": config.get_release_rule(repo),
                       "require_signatures": config.get_require_signatures(repo),
                       "assembly_variant_start": config.get_assembly_variant_start(repo),
                       "solidworks_version": config.get_solidworks_version(repo),
                       "currency": config.get_currency(repo)}
        except config.ConfigError as e:
            messagebox.showwarning("Vault settings", f"The settings file has a problem:\n\n{e}", parent=window)
            return
        installed = solidworks_versions.installed_year()
        chosen = vault_settings_dialog.VaultSettingsDialog(
            window, current, may_rename=self.identity.allows("rename_org")[0], installed=installed).show()
        changes = team_text.changed_settings(current, chosen)
        if not changes:
            return
        if changes.get("require_signatures") and not messagebox.askokcancel(
                "Require signed commits",
                "From now on, Litterbox refuses to upload any commit that is not signed by a key on the team list. "
                "Anyone who has not set up signing (Team > Signing...) will not be able to upload until they do."
                "\n\nTurn this on?", parent=window):
            return
        if changes.get("solidworks_version") and not messagebox.askokcancel(
                "SolidWorks version", team_text.solidworks_version_prompt(changes["solidworks_version"], installed),
                parent=window):
            return
        self.run_task(lambda: vault_settings.edit(repo, **changes), "Vault settings saved")

    def manage_projects(self, window):
        """Projects...: see the org's projects and add one (Admin and Owner, like the vault settings)."""
        if not self._may("manage_settings"):
            return
        repo = self.repo()
        try:
            config.apply(repo)
            current = config.get_projects(repo)
        except config.ConfigError as e:
            messagebox.showwarning("Projects", f"The settings file has a problem:\n\n{e}", parent=window)
            return
        chosen = projects_dialog.ProjectsDialog(window, repo, current).show()
        if not chosen:
            return
        if chosen[0] == "add":
            _what, name, prefix = chosen
            self.run_task(lambda: project_admin.add_project(repo, name, prefix), f"Project {name} added")
            return
        if chosen[0] == "edit":
            _what, name, new_name, new_prefix = chosen
            plan = lambda: project_admin.plan_change(repo, name, new_name, new_prefix)
            work = lambda: project_admin.edit_project(repo, name, new_name, new_prefix)
            done = f"Project {name} changed"
        else:
            _what, name = chosen
            plan = lambda: project_admin.plan_change(repo, name, delete=True)
            work = lambda: project_admin.delete_project(repo, name)
            done = f"Project {name} deleted"

        def ask(change):
            """Say what the change does to the parts (and refuse if any of them are checked out), then do it."""
            if change.checked_out:
                messagebox.showwarning("Projects", project_admin.checked_out_text(change), parent=window)
                return
            if messagebox.askyesno("Projects", project_text.change_text(change), parent=window,
                                   icon="warning"):
                self.run_task(work, done)

        self.run_task(plan, "", on_success=ask, refresh=False, label="Working out which parts change")

    def edit_workflow(self, window, documents=False):
        """Team > Part Workflows... (or, with documents=True, Doc Workflows...): the sign-off templates of the parts'
        actions or the documents' own, staged in the Team screen's draft."""
        if not self._may("manage_workflows") or window.draft is None:
            return
        draft = window.draft
        title = "Doc Workflows" if documents else "Part Workflows"
        if not draft.directory.roles:
            messagebox.showinfo(title, "This org has no roles yet. Add some in Team > Roles... first.",
                                parent=window)
            return

        def apply(ops, editor):
            wanted = editor.templates()
            notes = []
            for op in ops:
                if op["op"] == "set":
                    template = wanted[op["action"]][op["name"]]
                    notes += [f"{workflow_templates.label_of(op['action'])} {op['name']}: {n}"
                              for n in workflow_editing.role_warnings(template, draft.directory)]
            if notes and not messagebox.askyesno(
                    "Workflows", "\n".join(notes) + "\n\nUntil that is fixed a request will wait for an Admin "
                    "override. Keep this change anyway?", parent=window):
                return "Change the roles or the workflow, or press Cancel."

            def change(templates, _directory):
                workflow_editing.apply_ops(templates, ops)

            try:
                draft.stage_workflow(workflow_editor.ops_label(ops), change)
            except LitterboxError as e:
                return error_text.shorten(str(e))
            window.reload()
            return ""

        actions = workflow_templates.DOCUMENT_ACTIONS if documents else workflow_templates.PART_ACTIONS
        workflows_dialog.WorkflowsDialog(window, draft.directory.roles, draft.templates, apply=apply, actions=actions,
                                         title=title).show()

    def save_team(self, window):
        """The Team screen's Save: upload every staged change in one go."""
        draft = window.draft
        if draft is None or not draft.dirty:
            return
        repo = self.repo()

        def work():
            draft.save(repo)
            return team_identity.current(repo, probe=False)

        self.run_task(work, "Saved the team changes", on_success=self._team_changed, refresh=False)
