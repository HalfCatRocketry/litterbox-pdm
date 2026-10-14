"""
background_jobs.py - running work in the background so the window never freezes: the job queue,
its results, the status banner, and the errors it keeps until dismissed.
"""

import queue
import time
from tkinter import messagebox

from litterbox.errors import NothingToSaveError
from litterbox.gui import theme
from litterbox.gui.dialogs import error_details
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import error_text
from litterbox.gui.logic import job_text
from litterbox.gui.widgets import release_button
from litterbox.jobs import job_queue as jobs
from litterbox.user import settings


class BackgroundJobs:
    """running work in the background so the window never freezes: the job queue, (a part of the main window, App)."""

    def _watch_for_freezes(self, last=None):
        """Every quarter second; if the window was too busy to run this on time, say so in the log."""
        now = time.monotonic()
        if last is not None and now - last > 1.5:
            release_button.click_log(f"the window was frozen for {now - last:.1f}s")
        self.after(250, lambda: self._watch_for_freezes(now))

    @property
    def busy(self):
        """True while any job is queued, running or about to be shown. The window still works; only things that
        must not overlap with a running job (switching org, the Import window) check this."""
        return self.jobs.active()

    def _sync_busy(self):
        """Bring the banner, the buttons and the 'busy' marks in the list up to date with the job queue."""
        busy = self.busy
        if busy != self._was_busy:
            release_button.click_log(f"busy={busy}")
            self._was_busy = busy
            self.org_menu.configure(state="disabled" if busy else "normal")      # not while jobs run on this vault
            for window in self._team_windows():
                window.set_busy(busy)
        self._update_banner()
        if self.jobs.pending_parts() != self._shown_pending:
            self._render()                                                        # also updates the buttons
        else:
            self._update_buttons()

    def _update_banner(self):
        state = self.jobs.banner()
        color = {jobs.READY: theme.GREEN, jobs.WORKING: theme.BANNER_YELLOW, jobs.ERROR: theme.RED}[state.kind]
        text_color = "#1b1b1b" if state.kind == jobs.WORKING else "white"
        self.banner.configure(fg_color=color)
        self.banner_title.configure(text=state.title, text_color=text_color)
        self.banner_detail.configure(text=state.detail, text_color=text_color)
        if state.kind == jobs.ERROR:
            self.banner_details_button.grid(row=0, column=1, padx=(4, 4), pady=(8, 0))
            self.banner_dismiss_button.grid(row=0, column=2, padx=(0, 10), pady=(8, 0))
        else:
            self.banner_details_button.grid_remove()
            self.banner_dismiss_button.grid_remove()

    def show_errors(self):
        notes = self.jobs.errors()
        if notes:
            error_details.ErrorDetailsWindow(self, error_text.error_report_text(notes), self.dismiss_errors)

    def dismiss_errors(self):
        self.jobs.dismiss_errors()
        self._update_banner()
        self._say("Ready")

    def run_task(self, work, done_text, on_success=None, refresh=True, is_refresh=False, label="Working",
                 parts=(), kind="task"):
        """Queue work() to run in the background, after anything already queued. Then show done_text, call
        on_success(result) and refresh the list. `label` is what the banner says while it runs; `parts` are the
        parts it changes, which are marked busy until it is done."""
        ahead = self.jobs.active()
        job = jobs.Job(label=label, work=work, parts=tuple(str(p) for p in parts), kind=kind,
                       token=(done_text, on_success, refresh, is_refresh))
        if not ahead and settings.DEBUG:
            self._working_since = time.monotonic()
            self.after(1000, self._show_elapsed)
        self.jobs.submit(job)
        self._say(f"Queued: {label.lower()}" if ahead else f"{label}...")
        self._sync_busy()
        return True

    def _show_elapsed(self):
        """While a task runs, show how long it has taken, so a slow host looks slow rather than stuck."""
        if not self.jobs.working():
            return
        seconds = int(time.monotonic() - self._working_since)
        if seconds >= 3:
            self._say(f"Working... {seconds}s (the host may be slow)", "warn" if seconds >= 20 else "normal")
        self.after(1000, self._show_elapsed)

    def _poll_queue(self):
        try:
            self._drain_queue()
        finally:
            self.after(100, self._poll_queue)

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "update":
                    self._offer_update(payload)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass

    def _finish(self, outcome):
        """A job has finished: show how it went, run its follow-up, and free its parts."""
        job = outcome.job
        done_text, on_success, refresh, is_refresh = job.token
        try:
            self._show_outcome(job, outcome.result, outcome.error, done_text, on_success, refresh, is_refresh)
        except Exception as e:                      # a bug in a handler must not kill the window
            self._log(f"INTERNAL ERROR: {e!r}")
            self.jobs.add_error(job.label, f"Something unexpected went wrong: {e!r}",
                                error_text.error_advice("unexpected error"))
        finally:
            self.jobs.finished(job)
            self._sync_busy()

    def _show_outcome(self, job, result, error, done_text, on_success, refresh, is_refresh):
        if isinstance(error, NothingToSaveError):
            self.note = ""
            self._say("Nothing to save: nothing was different.")
            messagebox.showinfo("Nothing to save", str(error), parent=self._popup_parent())
        elif error:
            # A real problem: no pop-up (you may be busy elsewhere). The banner turns red; Details says what to do.
            self.note = ""
            self._log("ERROR: " + error)
            self.jobs.add_error(job.label, error, error_text.error_advice(error))
            self._say("Something went wrong. Press Details... on the red banner.", "error")
        else:
            if not is_refresh:
                self.note = done_text
            self._say(done_text)
            if on_success:
                on_success(result)
        if refresh:
            self.refresh()

    def _run_batch(self, action, plan, func):
        """Run an engine call for every planned part together: func(repo, parts) -> (done, failed), which does
        one download and one upload for the lot."""
        repo, targets = self.repo(), list(plan.targets)
        self.run_task(
            lambda: func(repo, targets),
            "", on_success=lambda result: self._after_batch(action, plan, result),
            label=job_text.job_label(action, len(targets)), parts=targets)

    def _after_batch(self, action, plan, result):
        done, failed = result
        self.note = action_rules.summary(action, len(done), len(failed), len(plan.skipped))
        self._say(self.note, "warn" if failed else "normal")
        if failed:
            messagebox.showerror("Litterbox", error_text.shorten(
                "\n\n".join(f"{pn}: {message}" for pn, message in failed)))

        if action == "checkout":
            self._warn_open_files([path for _pn, r in done for path in r.changed_upstream])
        elif action in ("checkin", "save"):
            nothing = [str(pn) for pn, r in done if not r.uploaded]
            if nothing:
                messagebox.showinfo("Nothing to upload", "There were no changes to save in: " + ", ".join(nothing))
        elif action == "undo":
            left = [name for _pn, names in done for name in names]
            if left:
                messagebox.showinfo(
                    "New files kept",
                    "These new files were never uploaded, so they were left in your cad folder:\n\n  " +
                    "\n  ".join(left))
