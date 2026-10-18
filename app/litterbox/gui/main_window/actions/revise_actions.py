"""
revise_actions.py - Revise and Cancel Revision.
"""

from tkinter import messagebox

from litterbox.gui.dialogs import text_input
from litterbox.gui.logic import confirmations
from litterbox.parts import cancel_revision
from litterbox.parts import revise


class ReviseActions:
    """Revise and Cancel Revision. (a part of the main window, App)."""

    def revise(self):
        plan = self._plan("revise")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: revise.revise_plan(repo, pn), "Checked what a revision would create",
                      on_success=lambda revise_plan: self._confirm_revise(repo, revise_plan), refresh=False)

    def _confirm_revise(self, repo, revise_plan):
        pn = revise_plan.pn
        if not revise_plan.ok:
            messagebox.showwarning("Can't revise yet", confirmations.revise_problem_text(pn, revise_plan.problems))
            return
        reason = text_input.ReasonDialog(self, f"Revise {pn.short}", confirmations.revise_confirm_text(revise_plan),
                              "Why is it being revised? (a few words)", "Revise").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: revise.revise(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Rev {revise_plan.new_revision} of {pn.short} is checked out to you")

    def cancel_revision(self):
        plan = self._plan("cancel_revision")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        self.run_task(lambda: cancel_revision.cancel_revision_plan(repo, pn), "Checked what cancelling would do",
                      on_success=lambda cancel_plan: self._confirm_cancel_revision(repo, cancel_plan),
                      refresh=False)

    def _confirm_cancel_revision(self, repo, cancel_plan):
        pn = cancel_plan.pn
        if not cancel_plan.ok:
            messagebox.showwarning("Can't cancel", confirmations.cancel_problem_text(pn, cancel_plan.problems))
            return
        reason = text_input.ReasonDialog(self, f"Cancel Rev {cancel_plan.revision} of {pn.short}",
                              confirmations.cancel_confirm_text(cancel_plan),
                              "Why is it being cancelled? (a few words)", "Cancel revision").show()
        if not reason:
            return
        self.pending_select = str(pn)
        self.run_task(lambda: cancel_revision.cancel_revision(repo, pn, reason, log=lambda text: self.queue.put(("log", text))),
                      f"Cancelled Rev {cancel_plan.revision} of {pn.short}")
