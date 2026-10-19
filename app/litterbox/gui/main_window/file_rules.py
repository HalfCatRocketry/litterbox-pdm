"""
file_rules.py - keeping the vault's file rules (.gitattributes, see vault/git_attributes.py) up to date: after a
refresh, if this Litterbox has newer rules than the vault, an Admin or the Owner is asked once per vault and session
whether to update them; anyone else is told an Admin needs to. Vault > Update file rules... does it later.
"""

from tkinter import messagebox

from litterbox.gui.logic import file_rules_text
from litterbox.vault import git_attributes


class FileRules:
    """the vault's file rules (a part of the main window, App)."""

    file_rules_outdated = False

    def _check_file_rules(self):
        """After a refresh: note whether the vault's rules are out of date, and ask (or say) once per session."""
        repo = self.repo()
        if not repo:
            return
        try:
            found, needed = git_attributes.needs_update(repo)
        except Exception:                               # never let this get in the way of the parts list
            return
        self.file_rules_outdated = needed
        if not needed:
            return
        asked = self.__dict__.setdefault("_file_rules_asked", set())
        if repo in asked:
            return
        asked.add(repo)
        allowed, _why = self.identity.allows("manage_settings")
        if allowed:
            self.update_file_rules(found=found)
        else:
            self._say(file_rules_text.ASK_AN_ADMIN, "warn")

    def update_file_rules(self, found=None):
        """Vault > Update file rules...: show what would change, and on yes update, commit and upload."""
        repo = self.repo()
        if not repo:
            return
        allowed, why = self.identity.allows("manage_settings")
        if not allowed:
            self._say(why, "warn")
            return
        old = git_attributes.read(repo)
        new = git_attributes.updated_text(old)
        if new == old.replace("\r\n", "\n"):
            self.file_rules_outdated = False
            self._say("This vault's file rules are up to date.")
            return
        found = git_attributes.vault_version(old) if found is None else found
        added = git_attributes.added_rules(old, new)
        question = file_rules_text.question(found, git_attributes.VERSION, git_attributes.change_lines(old, new),
                                            raises_minimum=any(r.endswith(" lockable") for r in added),
                                            minimum=git_attributes.MIN_LITTERBOX)
        if not messagebox.askyesno("Update file rules", question, parent=self):
            self._say("The file rules were not updated. Vault > Update file rules... does it later.")
            return

        def done(rules):
            self.file_rules_outdated = False

        self.run_task(lambda: git_attributes.update(repo), file_rules_text.done_text(len(added)), on_success=done,
                      label="Updating the file rules")
