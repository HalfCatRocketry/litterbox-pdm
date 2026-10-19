"""
org_switching.py - switching org (the org box in the header, and File > the orgs), Add org... and
Create new org... (an org's code and numbering are fixed when its vault is created, so there is no way to edit
them; the Owner can change its name in Vault Settings)
"""

from pathlib import Path
from tkinter import messagebox

from litterbox import diagnostics
from litterbox.core import part_number
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.gui.dialogs import clone_dialog
from litterbox.gui.dialogs import org_dialog
from litterbox.gui.logic import org_menu
from litterbox.user import settings
from litterbox.vault import clone as vault_clone
from litterbox.vault import config
from litterbox.vault import create_vault


class OrgSwitching:
    """switching org, Add org... and Create new org... (a part of the main window, App)."""

    @staticmethod
    def _detect_org(folder):
        try:
            return config.get_org(folder)
        except Exception:
            return None

    def _reload_org_menu(self):
        self.org_menu.configure(values=org_menu.org_choices(self.settings))
        self.org_var.set(self.org or "No org")
        self.folder_label.configure(text=self.repo())
        self.menu_bar.set_title(self._org_name())

    def on_org_chosen(self, choice):
        """An org was chosen (in the header or the File menu): switch to it (everything reloads). The setup entries
        are handled too, for older callers."""
        if choice == org_menu.ADD_ORG:
            self.add_org()
        elif choice == org_menu.CREATE_VAULT:
            self.create_vault()
        elif choice != self.org:
            self.switch_org(choice)
        self._reload_org_menu()

    def switch_org(self, org):
        if not all(screen.may_leave() for screen in self._team_windows()):
            return                                  # unsaved team changes, and the person wants to keep them
        self.org = org
        self.settings["last_org"] = org
        self.settings["repo"] = self.repo()
        settings.save(self.settings)
        self.rows, self.rows_by_pn, self.note = [], {}, ""
        self._render()                              # clear the list straight away
        self._update_counts()
        self._selection_changed()
        self._show_behind(0)
        self.folder_label.configure(text=self.repo())
        for screen in self._team_windows():
            screen.reload()
        if self.screen == "ecos":
            self._load_ecos()
        if Path(self.repo()).is_dir():
            self.refresh()
        else:
            self._say(f"The vault folder for {org} wasn't found: {self.repo()}. Use File > Add org... to copy it to this computer again.", "warn")

    def add_org(self):
        """Add org...: paste the URL of a vault on your Git host. Litterbox clones it into its own folder (see
        vault_clone.py), reads the org code and numbering from it, and opens it. A brand-new vault is made with
        Create new org... instead."""
        known = org_menu.known_orgs(self.settings)
        url = clone_dialog.CloneDialog(self, settings.ROOT).show()
        if not url:
            return
        target, problem = org_menu.plan_add_org(url, settings.ROOT, known)
        if problem:
            messagebox.showwarning("Add org", problem, parent=self)
            return

        def work():
            if target.exists():
                org, _problem = org_menu.inspect_vault_folder(target)
                if org:
                    return target                              # cloned already (an earlier try): just use it
                if any(target.iterdir()):
                    raise LitterboxError(f"{target} already exists and isn't a vault. Rename or remove it, "
                                                "then try again.")
            vault_clone.clone(url.strip(), target, settings.downloads_on_demand(self.settings))
            try:
                read_only.enforce_read_only(target)
            except LitterboxError as e:
                diagnostics.LOG(f"WARNING: could not set the files read-only: {e}")
            return target

        def cloned(folder):
            org, problem = org_menu.inspect_vault_folder(folder)
            if problem:
                messagebox.showwarning("Add org", f"The vault was copied to {folder}, but:\n\n{problem}",
                                       parent=self)
                return
            org_menu.remember_org(self.settings, org, str(folder))
            settings.save(self.settings)
            self._reload_org_menu()
            self.note = f"Added {org}"
            self.switch_org(org)

        self.run_task(work, "Vault copied to this computer", on_success=cloned, refresh=False,
                      label="Cloning the vault (this can take a while)")

    def create_vault(self):
        """Create new org...: paste the URL of an empty repository on your Git host. After a last check of the
        settings (they can't be changed later), Litterbox clones it into its own folder, like Add org..., and turns
        it into a vault (see create_vault.py)."""
        if not messagebox.askyesno("Create new org", org_menu.CREATE_VAULT_INTRO, parent=self):
            return
        result = org_dialog.OrgDialog(self, settings.ROOT, base_digits=part_number.NEW_VAULT_BASE_DIGITS,
                                      variant_digits=part_number.DEFAULT_VARIANT_DIGITS).show()
        if not result:
            return
        url, org, start, base_digits, variant_digits, org_name, assembly = result
        target, problem = org_menu.plan_add_org(url, settings.ROOT, org_menu.known_orgs(self.settings))
        checked = create_vault.check_settings(org, start, base_digits, variant_digits, assembly)
        problems = ([problem] if problem else []) + checked.problems
        if problems:
            messagebox.showerror("Create new org", "\n\n".join(problems), parent=self)
            return
        if not messagebox.askyesno("Create new org", org_menu.fixed_settings_text(
                checked.org, org_name, start, base_digits, variant_digits, checked.warnings, assembly), parent=self):
            return

        def work():
            folder = vault_clone.clone_or_reuse(url, target, settings.downloads_on_demand(self.settings))
            return folder, create_vault.create(folder, org, start, base_digits, variant_digits, org_name=org_name,
                                               assembly_variant_start=assembly)

        def made(done):
            folder, created = done
            org_menu.remember_org(self.settings, created.org, str(folder))
            settings.save(self.settings)
            self._reload_org_menu()
            self.switch_org(created.org)
            messagebox.showinfo("Create new org", org_menu.vault_created_text(created), parent=self)

        self.run_task(work, f"Created the {checked.org} vault", on_success=made, refresh=False,
                      label="Copying the empty repository and setting up the vault")
