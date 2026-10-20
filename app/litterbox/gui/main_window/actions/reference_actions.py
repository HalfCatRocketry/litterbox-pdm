"""
reference_actions.py - References...: showing what a part uses and where it is used, and
updating out-of-date references; Update BOM on the BOM tab.
"""

from tkinter import messagebox

from litterbox.errors import LitterboxError
from litterbox.gui.logic import error_text
from litterbox.gui.logic import reference_text
from litterbox.gui.windows import references_window
from litterbox.parts import part_status
from litterbox.references import reference_model
from litterbox.references import reference_queries
from litterbox.references import reference_replace
from litterbox.references import reference_rescan


class ReferenceActions:
    """References...: showing what a part uses and where it is used, and (a part of the main window, App)."""

    def _offer_reference_review(self, pn, row, rev):
        """An assembly in work that uses out-of-date parts: offer to review them first. True if the review opened."""
        if row.kind not in ("ok", "mine", "unclaimed") or rev != row.revision:
            return False
        try:
            stale = [u for u in reference_queries.uses(self.repo(), pn, rev) if u.replaceable]
        except LitterboxError:
            return False
        if not stale:
            return False
        if messagebox.askyesno("Parts out of date", reference_text.stale_open_text(pn, stale)):
            self._load_references(pn)
            return True
        return False

    def show_references(self):
        plan = self._plan("references")
        if plan:
            self._load_references(plan.targets[0])

    def _load_references(self, pn, window=None):
        """Open the References window for a part (or, with `window`, refresh the one that is already open)."""
        repo = self.repo()

        def load():
            records = reference_model.load_records(repo)
            outdated = reference_queries.outdated_parts(repo, records)
            return (records[pn].name if pn in records else "", reference_queries.uses(repo, pn, None, records),
                    reference_queries.where_used(repo, pn, records), pn in outdated, [p for p in outdated if p != pn])

        def show(r):
            if window is not None and window.winfo_exists():
                window.show(r[0], r[1], r[2], r[3], r[4])
            else:
                references_window.ReferencesWindow(self, pn, r[0], r[1], r[2], self._replace_references,
                                 this_outdated=r[3], others_outdated=r[4],
                                 on_update=lambda win, pns: self._update_references(pn, pns, win))

        self.run_task(load, "", refresh=False, is_refresh=True, on_success=show)

    def _update_references(self, pn, pns, window):
        """Read the assemblies' files (starting SolidWorks if it is not running) and store what they use.
        The References window stays open and is refreshed when this finishes."""
        repo = self.repo()

        def work():
            try:
                results = reference_rescan.rescan(repo, pns, log=lambda text: self.queue.put(("log", text)))
                return results, part_status.get_status(repo), ""
            except Exception as e:                       # the window must be given back either way
                return None, None, str(e)

        def done(result):
            results, rows, error = result
            if error:
                if window.winfo_exists():
                    window.set_idle()
                messagebox.showerror("Update references", error_text.shorten(error))
                return
            self._show_rows(rows)
            text, problems = reference_text.update_summary(results)
            if problems:
                messagebox.showwarning("Update references", text)
            self._load_references(pn, window)

        if not self.run_task(work, "Updated the lists of parts used", on_success=done, refresh=False):
            window.set_idle()

    def update_bom(self):
        """Update BOM on the BOM tab: read the highlighted assembly's files again and count its parts. SolidWorks
        is used if it is open; if not, it is started out of sight and closed afterwards."""
        pn = self.pane_pn
        if pn is None:
            return
        repo = self.repo()

        def work():
            results = reference_rescan.rescan(repo, [pn], log=lambda text: self.queue.put(("log", text)))
            return results, part_status.get_status(repo)

        def done(result):
            results, rows = result
            self._show_rows(rows)                         # the pane reads the BOM again
            text, problems = reference_text.update_summary(results)
            if problems:
                messagebox.showwarning("Update BOM", text)

        self.run_task(work, "Updated the BOM", on_success=done, refresh=False, label="Counting parts with SolidWorks",
                      parts=(pn,))

    def _replace_references(self, items):
        repo = self.repo()
        count = len({item.parent for item in items})
        if not messagebox.askokcancel(
                "Replace references",
                f"Point {count} assembl{'y' if count == 1 else 'ies'} at the latest released revision of the "
                "parts you ticked?\n\nAssemblies nobody has checked out are checked out, changed and checked "
                "back in. An assembly you already have checked out is changed in your copy and left for you to "
                "check in. Assemblies checked out by someone else are skipped."):
            return

        def done(results):
            text, problems = reference_text.replace_summary(results)
            (messagebox.showwarning if problems else messagebox.showinfo)("Replace references", text)

        self.run_task(lambda: reference_replace.replace_references(
            repo, items, log=lambda text: self.queue.put(("log", text))), "Updated references", on_success=done)
