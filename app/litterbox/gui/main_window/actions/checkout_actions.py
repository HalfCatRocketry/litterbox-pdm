"""
checkout_actions.py - Check Out (and, after it, making files SolidWorks already has open writable), Undo Checkout
and Break Checkout.
"""

from pathlib import Path
from tkinter import messagebox

from litterbox import diagnostics
from litterbox.core import file_types
from litterbox.cad import solidworks_versions
from litterbox.cad import cad_programs
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import solidworks_text
from litterbox.parts import break_checkout as breaking
from litterbox.parts import checkout
from litterbox.parts import undoing
from litterbox.vault import config


class CheckoutActions:
    """Check Out (and making files SolidWorks already has open writable), Undo Checkout and Break Checkout. One part of
    the main window (App)."""

    def break_checkout(self):
        """Break Checkout... (Admin and Owner): take a part back from whoever has it checked out."""
        plan = self._plan("break_checkout")
        if not plan:
            return
        pn = plan.targets[0]
        who = self.rows_by_pn[pn].locked_by or "someone"
        reason = self._ask_reason(f"Why is {who}'s checkout of {pn} being broken?", "Break Checkout")
        if not reason:
            return
        if not messagebox.askyesno("Break Checkout", checkin_text.break_checkout_prompt(pn, who)):
            return
        repo = self.repo()
        self.run_task(lambda: breaking.break_checkout(repo, pn, reason), f"Broke {who}'s checkout of {pn}",
                      label=f"Breaking the checkout of {pn}", parts=[pn])

    def check_out(self):
        plan = self._plan("checkout")
        if plan and self._older_solidworks_ok():
            self._run_batch("checkout", plan, checkout.checkout_many)

    def _after_checkout(self, done):
        """After a check-out (`done`: [(pn, CheckoutResult)]): files of these parts that SolidWorks already had open
        read-only become writable (cad_programs.make_writable), so they can be saved without reloading by hand.
        Then the note about files the check-out updated, for those that weren't just reloaded. Best effort: nothing
        here can undo or fail the check-out."""
        repo = self.repo()
        changed = [path for _pn, result in done for path in result.changed_upstream]
        files = [rel for pn, _result in done for rel in self._working_files(pn)
                 if file_types.extension(rel) in file_types.CAD_EXTENSIONS]
        if not files:
            self._warn_open_files(changed)
            return
        paths = [str(Path(repo) / rel) for rel in files]

        def look():
            try:
                return cad_programs.open_read_only(paths)
            except Exception as e:                      # SolidWorks busy or gone: say nothing, just log it
                diagnostics.LOG(f"Couldn't ask SolidWorks what it has open after a check-out: {e}")
                return None

        self.run_task(look, "", on_success=lambda found: self._make_writable(found or [], changed), refresh=False,
                      is_refresh=True, label="Looking at what SolidWorks has open")

    def _working_files(self, pn):
        row = self.rows_by_pn.get(pn)
        return history_text.row_revisions(row).get(row.revision, []) if row is not None else []

    def _make_writable(self, found, changed):
        repo = self.repo()
        switch, reload, ask = solidworks_text.writable_plan(found, repo, changed)
        if ask and not messagebox.askyesno("Reload in SolidWorks", solidworks_text.reload_unsaved_question(ask),
                                           parent=self):
            reload = [path for path in reload if path not in ask]
        wanted = switch + reload
        if not wanted:
            self._warn_open_files(changed)
            return

        def finished(result):
            made, failed = result
            said = []
            if made:
                said.append(solidworks_text.writable_done_text(made))
            if failed:
                self._log("SolidWorks: couldn't make writable: " + "; ".join(f"{p} ({why})" for p, why in failed))
                said.append(solidworks_text.writable_failed_text(failed))
            self.note = ". ".join(([self.note] if self.note else []) + said)
            self._say(self.note, "warn" if failed else "normal")
            self._warn_open_files(solidworks_text.still_old(repo, changed, made))

        self.run_task(lambda: cad_programs.make_writable(wanted, reload), "", on_success=finished, refresh=False,
                      is_refresh=True, label="Making open files writable in SolidWorks")

    def _older_solidworks_ok(self):
        """Warn, once per org each time Litterbox runs, when this computer's SolidWorks is older than the org's.
        True to go ahead. (A newer one is refused by the check-out itself.)"""
        repo = str(self.repo())
        warned = self.__dict__.setdefault("_warned_older_solidworks", set())
        if repo in warned:
            return True
        try:
            org_year = config.get_solidworks_version(repo)
        except config.ConfigError:
            return True                                  # the check-out reports a broken settings file
        if not org_year:
            return True
        installed = solidworks_versions.installed_year()
        if solidworks_versions.compare(org_year, installed) != solidworks_versions.OLDER:
            return True
        if not messagebox.askokcancel("SolidWorks version",
                                      solidworks_versions.older_text(org_year, installed) + "\n\nCheck out anyway?"):
            return False
        warned.add(repo)
        return True

    def undo_checkout(self):
        plan = self._plan("undo")
        if not plan:
            return
        if not messagebox.askyesno("Undo checkout", checkin_text.undo_prompt(plan.targets)):
            return
        self._run_batch("undo", plan, undoing.undo_checkout_many)
