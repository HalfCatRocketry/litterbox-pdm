"""
problem_reports.py - Help > Report a problem (and Report... in the error Details window): ask what you were doing,
make the report (user/bug_report.py) and open an email with it (user/report_mail.py). Also catches errors in the
window's own code (report_callback_exception), which would otherwise only reach a console nobody sees: they are kept
for the report and shown in the red status bar.
"""

import threading
import traceback
from tkinter import messagebox

from litterbox import diagnostics
from litterbox.cad import opener
from litterbox.errors import LitterboxError
from litterbox.gui.dialogs import bug_report_dialog
from litterbox.gui.logic import bug_report_text
from litterbox.gui.logic import error_text
from litterbox.user import bug_report
from litterbox.user import report_mail


class ProblemReports:
    """Problem reports. One part of the main window (App)."""

    def report_problem(self, parent=None):
        """Ask for the comment, then make and send the report on a thread of its own: not through the job queue,
        since the problem being reported may be a job that never finishes."""
        problems = [(note.label, note.message) for note in self.jobs.errors()]
        repo, org = self.repo(), self.org
        answer = bug_report_dialog.BugReportDialog(
            parent or self, bug_report.ADDRESS, len(problems), lambda leave_out: bug_report.contents(repo, leave_out),
            bug_report.TAKEN_OUT, bug_report.NEVER_IN, bug_report.PRIVACY_URL).show()
        if answer is None:
            return
        comment, leave_out = answer
        self._say("Making the problem report...")

        def work():
            try:
                path = bug_report.make(comment, repo, problems, leave_out=leave_out)
                how = report_mail.send(bug_report.ADDRESS, bug_report.subject(org),
                                       bug_report.body(comment, bug_report.facts()), path)
                self.queue.put(("call", lambda: self._report_sent(how, path)))
            except Exception as e:
                self.queue.put(("call", lambda: self._report_failed(e)))

        threading.Thread(target=work, name="problem report", daemon=True).start()

    def _report_sent(self, how, path):
        self._say("The problem report is ready to send.")
        text = bug_report_text.sent_text(how, path)
        if how != report_mail.OUTLOOK:                  # Explorer already shows the report, to attach
            messagebox.showinfo("Report a problem", text, parent=self)
        elif messagebox.askyesno("Report a problem", f"{text}\n\n{bug_report_text.OPEN_QUESTION}", parent=self):
            try:
                opener.open_path(path)
            except LitterboxError as e:
                messagebox.showerror("Report a problem", str(e), parent=self)

    def _report_failed(self, error):
        self._say("The problem report couldn't be made.", "warn")
        messagebox.showerror("Report a problem", f"The report couldn't be made: {error}\n\nPlease email "
                                                 f"{bug_report.ADDRESS} and say what happened.", parent=self)

    def report_callback_exception(self, kind, value, trace):
        """Tk calls this when the window's own code fails (a button's command, say): keep it for a problem
        report and show it in the red status bar, instead of losing it."""
        text = "".join(traceback.format_exception(kind, value, trace))
        diagnostics.note_unexpected("using the window", text)
        try:
            self.jobs.add_error("Using the window", f"Unexpected error: {value!r}",
                                error_text.error_advice("unexpected error"))
            self._update_banner()
            self._say("Something went wrong. Press Details... in the red status bar.", "error")
        except Exception:
            pass
