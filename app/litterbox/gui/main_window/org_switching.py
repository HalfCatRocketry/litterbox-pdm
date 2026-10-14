"""
org_switching.py - the org box: switching org, Add org..., Org setup... and Create new vault...
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
from litterbox.vault import config_write
from litterbox.vault import create_vault


class OrgSwitching:
    """the org box: switching org, Add org..., Org setup... and Create new vault... (a part of the main window, App)."""

    @staticmethod
    def _detect_org(folder):
        try:
            return config.get_org(folder)
        except Exception:
            return None

    def _reload_org_menu(self):
        self.org_menu.configure(values=org_menu.org_menu_values(self.settings))
        self.org_var.set(self.org or "No org")
        self.folder_label.configure(text=self.repo())

    def on_org_chosen(self, choice):
        """The dropdown changed: switch org (everything reloads) or open the setup pop-up."""
        if choice == org_menu.ADD_ORG:
            self.add_org()
        elif choice == org_menu.CREATE_VAULT:
            self.create_vault()
        elif choice == org_menu.EDIT_ORG:
            self._org_setup(self.org)
        elif choice != self.org:
            self.switch_org(choice)
        self._reload_org_menu()

    def switch_org(self, org):
        self.org = org
        self.settings["last_org"] = org
        self.settings["repo"] = self.repo()
        settings.save(self.settings)
        self.rows, self.rows_by_pn, self.note = [], {}, ""
        self._render()                              # clear the list straight away
        self.folder_label.configure(text=self.repo())
        if Path(self.repo()).is_dir():
            self.refresh()
        else:
            self._say(f"The vault folder for {org} wasn't found: {self.repo()}. Use Org setup to fix it.", "warn")

    def add_org(self):
        """Add org...: paste the URL of a vault on your Git host. Litterbox clones it into its own folder (see
        vault_clone.py), reads the org code and numbering from it, and opens it. A brand-new vault is made with
        Create new vault... instead."""
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
            vault_clone.clone(url.strip(), target)
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

    def _org_setup(self, org):
        """Edit an org: its code, vault folder and starting part number."""
        folder = org_menu.known_orgs(self.settings).get(org, "") if org else ""
        start, base_digits, variant_digits = 1, part_number.DEFAULT_BASE_DIGITS, part_number.DEFAULT_VARIANT_DIGITS
        if folder and Path(folder).is_dir():
            try:
                start = config.get_start_number(folder)
                base_digits, variant_digits = config.get_digits(folder)
            except config.ConfigError:
                pass
        result = org_dialog.OrgDialog(self, org or "", folder, start, base_digits, variant_digits,
                           title=f"Org setup - {org}" if org else "Org setup").show()
        if not result:
            return
        new_org, new_folder, new_start, new_base_digits, new_variant_digits = result
        try:
            config_write.save(new_folder, org=new_org, start_number=new_start,
                        base_digits=new_base_digits, variant_digits=new_variant_digits)
        except (config.ConfigError, OSError) as e:
            messagebox.showerror("Org setup", f"Could not save the settings in the vault:\n\n{e}", parent=self)
            return
        if org and org != new_org:
            orgs = org_menu.known_orgs(self.settings)
            orgs.pop(org, None)
            self.settings["orgs"] = orgs
        org_menu.remember_org(self.settings, new_org, new_folder)
        settings.save(self.settings)
        self.note = ("Saved. Commit and push .litterbox/config.yaml so your team gets the same org setup")
        self.switch_org(new_org)

    def create_vault(self):
        """Create new vault...: turn an empty cloned repository into a vault (see init_vault.py)."""
        if not messagebox.askyesno("Create new vault", org_menu.CREATE_VAULT_INTRO, parent=self):
            return
        result = org_dialog.OrgDialog(self, "", "", 1, part_number.NEW_VAULT_BASE_DIGITS, part_number.DEFAULT_VARIANT_DIGITS,
                           title="Create new vault", save_text="Create").show()
        if not result:
            return
        org, folder, start, base_digits, variant_digits = result
        checked = create_vault.plan(folder, org, start, base_digits, variant_digits)
        if not checked.ok:
            messagebox.showerror("Create new vault", "\n\n".join(checked.problems), parent=self)
            return
        if checked.warnings and not messagebox.askyesno(
                "Create new vault", "\n\n".join(checked.warnings) + "\n\nCreate the vault anyway?", parent=self):
            return

        def made(created):
            org_menu.remember_org(self.settings, created.org, folder)
            settings.save(self.settings)
            self._reload_org_menu()
            self.switch_org(created.org)
            messagebox.showinfo("Create new vault", org_menu.vault_created_text(created), parent=self)

        self.run_task(lambda: create_vault.create(folder, org, start, base_digits, variant_digits),
                      f"Created the {checked.org} vault", on_success=made, refresh=False)
