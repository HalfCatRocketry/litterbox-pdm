"""
checkin_actions.py - Check In and Save Progress: the comment, parts with no changes, and
watching the files for a save after the click.
"""

from tkinter import messagebox

from litterbox.gui.dialogs import confirm_dialogs
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import solidworks_text
from litterbox.parts import checkin
from litterbox.parts import part_changes
from litterbox.references import reference_reader


class CheckinActions:
    """Check In and Save Progress: the comment, parts with no changes, and (a part of the main window, App)."""

    def _ask_comment_and_check_in(self, action, plan, allow_unchanged=frozenset()):
        """Ask for a comment, then check in (or save progress on) the planned parts."""
        keep_lock = action == "save"
        comment = self._ask("Describe your changes:\n\n" + checkin_text.CHECKIN_CAUTION,
                            "Save Progress" if keep_lock else "Check In")
        if comment is None:                                  # cancelled
            return
        comment = comment.strip() or "Update"
        reader = reference_reader.make_reader(log=lambda text: self.queue.put(("log", text)))
        snapshot = self._watch_files(plan.targets)
        self._run_batch(action, plan, lambda repo, pns: checkin.checkin_many(
            repo, pns, comment, keep_lock=keep_lock, allow_unchanged=allow_unchanged, references_reader=reader,
            snapshot=snapshot))

    def _watch_files(self, targets):
        """Remember the files' sizes and times now, so a part saved after this click is not uploaded half way
        (see file_snapshot.py). Never stops the check-in: if it can't be done, there is just no protection."""
        try:
            return checkin.watch_files(self.repo(), {pn: self.rows_by_pn[pn].revision for pn in targets})
        except Exception as e:
            self._log(f"Could not watch the files for changes: {e!r}")
            return None

    def _check_in(self, keep_lock):
        action = "save" if keep_lock else "checkin"
        plan = self._plan(action)
        if not plan:
            return
        files = [f for pn in plan.targets for f in getattr(self.rows_by_pn.get(pn), "files", [])]
        if not self._saved_in_solidworks(files, "save progress" if keep_lock else "check in"):
            return
        if keep_lock:                       # saving progress with no changes just does nothing
            self._ask_comment_and_check_in(action, plan)
            return
        # Check In: first look for parts with nothing to upload, and ask before going ahead.
        repo = self.repo()
        self.run_task(
            lambda: part_changes.change_reports(repo, plan.targets), "",
            on_success=lambda reports: self._confirm_unchanged(plan, reports),
            refresh=False, is_refresh=True)

    def _confirm_unchanged(self, plan, reports):
        unchanged = checkin_text.parts_without_changes(reports)
        if unchanged:
            dialog = confirm_dialogs.ConfirmDialog(
                self, "No changes detected", "No changes were detected in these files:",
                checkin_text.unchanged_lines(unchanged),
                note="Continue will still check the part in: the check-in is recorded in its log, "
                     "uploaded, and your lock is released. Cancel leaves everything as it is.",
                confirm_text="Continue")
            if not dialog.show():
                self._say("Check-in cancelled. Nothing was changed.", "warn")
                return
        self._ask_comment_and_check_in("checkin", plan, frozenset(pn for pn, _files in unchanged))

    def check_in(self):
        self._check_in(keep_lock=False)

    def save_progress(self):
        self._check_in(keep_lock=True)

    def _warn_open_files(self, paths):
        still_open = self._open_in_solidworks(paths)
        if still_open is not None:                  # watching SolidWorks: name only the files that are open there
            if still_open:
                messagebox.showinfo("Newer versions downloaded", solidworks_text.reopen_note(still_open))
            return
        names = checkin_text.cad_changes(paths)
        if names:
            messagebox.showinfo(
                "Newer versions downloaded",
                "These files were updated:\n\n  " + "\n  ".join(names) +
                "\n\nIf any of them are open in SolidWorks, close and reopen them "
                "so you aren't looking at an old copy.")
