"""
checkout_actions.py - Check Out (and, after it, making files SolidWorks already has open writable), Refresh Read
State, Undo Checkout and Break Checkout.
"""

import os
from pathlib import Path
from tkinter import messagebox

from litterbox import diagnostics
from litterbox.core import file_types
from litterbox.cad import solidworks_versions
from litterbox.cad import cad_programs
from litterbox.cad import open_documents
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import solidworks_text
from litterbox.parts import break_checkout as breaking
from litterbox.parts import checkout
from litterbox.parts import undoing
from litterbox.vault import config


class CheckoutActions:
    """Check Out (and making files SolidWorks already has open writable), Refresh Read State, Undo Checkout and Break
    Checkout. One part of the main window (App)."""

    stale_in_cad = frozenset()      # keys of open files a check-out updated on disk, but that weren't reloaded

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
            self._mark_stale(ask, [])
        wanted = switch + reload
        if not wanted:
            self._warn_open_files(changed)
            return

        def finished(result):
            made, failed = result
            self._mark_stale([path for path, _why in failed if path in reload], made)
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

    def _mark_stale(self, stale, fresh):
        """Remember the open documents (full paths) that still show an older copy than the file on disk, so Refresh
        Read State reloads them rather than letting them be saved over it; forget those just loaded again."""
        self.stale_in_cad = ((set(self.stale_in_cad) | {open_documents.key(p) for p in stale})
                             - {open_documents.key(p) for p in fresh})

    def refresh_read_state(self):
        """Refresh Read State (Part menu): make every document from this vault that SolidWorks has open read-only or
        writable to match its file on disk, which is writable only while you have the part checked out (or it isn't
        in the vault's records yet, like a file just saved under a new name)."""
        repo = self.repo()
        if not repo:
            return

        def look():
            found = cad_programs.open_all()
            if found is None:
                return None
            found = [doc for doc in found if solidworks_text.in_vault(repo, doc.path)]
            writable = {open_documents.key(doc.path): os.access(doc.path, os.W_OK)
                        for doc in found if os.path.isfile(doc.path)}
            return found, writable

        self.run_task(look, "", on_success=self._refresh_read_state, refresh=False, is_refresh=True,
                      label="Looking at what SolidWorks has open")

    def _refresh_read_state(self, looked):
        if looked is None:
            self._say(solidworks_text.read_state_unchanged_text(False))
            return
        found, writable = looked
        switch, reload, ask, lock = solidworks_text.read_state_plan(found, writable, self.stale_in_cad)
        if ask and not messagebox.askyesno("Reload in SolidWorks", solidworks_text.reload_unsaved_question(ask),
                                           parent=self):
            reload = [path for path in reload if path not in ask]
        if not switch + reload + lock:
            self._say(solidworks_text.read_state_unchanged_text(True))
            return
        unsaved = [doc.path for doc in found if doc.unsaved and doc.path in lock]

        def change():
            made = cad_programs.make_writable(switch + reload, reload) if switch + reload else ([], [])
            locked = cad_programs.make_read_only(lock) if lock else ([], [])
            return made, locked

        def finished(result):
            (made, failed), (locked, lock_failed) = result
            self._mark_stale([path for path, _why in failed if path in reload], made)
            said = []
            if made:
                said.append(solidworks_text.writable_done_text(made))
            if locked:
                said.append(solidworks_text.read_only_done_text(locked, [p for p in unsaved if p in locked]))
            if failed:
                said.append(solidworks_text.writable_failed_text(failed))
            if lock_failed:
                said.append(solidworks_text.read_only_failed_text(lock_failed))
            if failed or lock_failed:
                self._log("SolidWorks: couldn't refresh the read state: " +
                          "; ".join(f"{p} ({why})" for p, why in failed + lock_failed))
            self._say(". ".join(said), "warn" if failed or lock_failed else "normal")

        self.run_task(change, "", on_success=finished, refresh=False, is_refresh=True,
                      label="Refreshing the read state in SolidWorks")

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
