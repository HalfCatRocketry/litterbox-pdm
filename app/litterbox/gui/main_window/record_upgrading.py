"""
record_upgrading.py - upgrading the vault's records to the record format this Litterbox writes (vault/record_upgrade.py):
after a refresh, if the vault needs it, an Admin or the Owner is asked once per vault and session; anyone else is told
an Admin needs to. Vault > Upgrade records... does it later.
"""

from tkinter import messagebox

from litterbox import diagnostics
from litterbox.gui.logic import record_upgrade_text
from litterbox.vault import record_upgrade


class RecordUpgrade:
    """Upgrading the vault's records. One part of the main window (App)."""

    records_outdated = False

    def _check_record_upgrade(self):
        """After a refresh: note whether the vault's records need upgrading, and ask (or say) once per session."""
        repo = self.repo()
        if not repo:
            return
        try:
            needed = record_upgrade.needs_upgrade(repo)
        except Exception:                               # never let this get in the way of the parts list
            return
        self.records_outdated = needed
        if not needed:
            return
        asked = self.__dict__.setdefault("_record_upgrade_asked", set())
        if repo in asked:
            return
        asked.add(repo)
        allowed, _why = self.identity.allows(record_upgrade.PERMISSION)
        if allowed:
            self.upgrade_records()
        else:
            self._say(record_upgrade_text.ASK_AN_ADMIN, "warn")

    def upgrade_records(self):
        """Vault > Upgrade records...: find out what would change, ask, then upgrade and upload."""
        repo = self.repo()
        if not repo:
            return
        allowed, why = self.identity.allows(record_upgrade.PERMISSION)
        if not allowed:
            self._say(why, "warn")
            return
        self.run_task(lambda: record_upgrade.plan(repo), "", on_success=lambda plan: self._ask_upgrade(repo, plan),
                      refresh=False, label="Looking at the records")

    def _ask_upgrade(self, repo, plan):
        if not plan.outdated and not plan.raise_minimum:
            self.records_outdated = False
            self._say(record_upgrade_text.UP_TO_DATE)
            return
        if not messagebox.askyesno("Upgrade records", record_upgrade_text.question(plan), parent=self):
            self._say(record_upgrade_text.NOT_NOW)
            return
        self.run_task(lambda: record_upgrade.upgrade(repo), "", on_success=self._after_upgrade,
                      label="Upgrading the records")

    def _after_upgrade(self, result):
        self.records_outdated = bool(result.checked_out or result.errors)
        for pn, why in result.errors.items():
            diagnostics.LOG(f"{pn} could not be upgraded: {why}")
        self.note = record_upgrade_text.done_text(result)
        self._say(self.note, "warn" if result.errors else "normal")
