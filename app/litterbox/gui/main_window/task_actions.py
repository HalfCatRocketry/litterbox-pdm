"""
task_actions.py - My Tasks and sign-off workflows: signing, rejecting, completing, withdrawing,
overriding and reassigning, and starting a workflow from a button.
"""

from tkinter import messagebox

from litterbox.errors import LitterboxError
from litterbox.gui.dialogs.workflow import reassign_dialog
from litterbox.gui.dialogs.workflow import request_dialog
from litterbox.gui.logic import error_text
from litterbox.gui.logic import task_text
from litterbox.gui.windows import tasks_window
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates


class TaskActions:
    """My Tasks and sign-off workflows: signing, rejecting, completing, withdrawing, (a part of the main window, App)."""

    def _task_windows(self):
        return [w for w in self.winfo_children() if isinstance(w, tasks_window.TasksWindow) and w.winfo_exists()]

    def _refresh_tasks(self):
        """Update the My Tasks button's count and any open My Tasks window."""
        button = getattr(self, "tasks_button", None)
        if button is None:
            return
        tasks = workflow_tasks.tasks_from_rows(self.rows, self.identity)
        button.configure(text=task_text.tasks_button_text(workflow_tasks.count_for_me(tasks)))
        for window in self._task_windows():
            window.reload()

    def show_tasks(self):
        windows = self._task_windows()
        if windows:
            windows[0].reload()
            windows[0].lift()
            return
        tasks_window.TasksWindow(self)

    def task_sign(self, task):
        comment = self._ask("Comment (optional):", f"Approve: {task.label}")
        if comment is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_signoff.sign_off(repo, pns, comment), f"Signed off {task.label}",
                      on_success=lambda result: self._signed(task, result))

    def _signed(self, task, result):
        text, _warn = task_text.signoff_result_text(result)
        if text:
            messagebox.showwarning("Sign-off saved", text)
        elif result.completed:
            self.note = f"Signed off; {workflow_templates.label_of(task.action)} done on {len(result.completed)} part" \
                        f"{'s' if len(result.completed) != 1 else ''}"

    def task_reject(self, task):
        reason = self._ask_reason("Why are you rejecting it? The person who asked will see this.",
                                  f"Reject: {task.label}")
        if reason is None:
            return
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_responses.reject(repo, pns, reason), f"Rejected {task.label}")

    def task_complete(self, task):
        repo, pns = self.repo(), task.pns
        label = workflow_templates.label_of(task.action)
        if messagebox.askokcancel(f"{label} {task.label}", f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow_signoff.complete_many(repo, pns), f"{label} done: {task.label}")

    def task_withdraw(self, task):
        repo, pns = self.repo(), task.pns
        if messagebox.askyesno(f"Withdraw {task.label}", "Withdraw this request? The sign-offs so far are "
                                                         "discarded, and you can ask again later."):
            self.run_task(lambda: workflow_responses.withdraw(repo, pns), f"Withdrew the request for {task.label}")

    def task_override(self, task):
        label = workflow_templates.label_of(task.action)
        reason = self._ask_reason(f"Why {label.lower()} without the sign-offs? This is recorded permanently.",
                                  f"Admin override: {label.lower()} {task.label}")
        if reason is None:
            return
        repo, pns, action = self.repo(), task.pns, task.action
        if messagebox.askokcancel(f"{label} {task.label}", f"{label} without the required sign-offs?\n\nReason: "
                                                           f"{reason}\n\nThis is recorded as an Admin override."):
            self.run_task(lambda: workflow_signoff.override(repo, pns, reason, action=action),
                          f"{label} done: {task.label} (Admin override)")

    def task_reassign(self, task):
        directory = self.identity.directory
        if directory is None:
            return
        chosen = reassign_dialog.ReassignDialog(self, task, directory).show()
        if chosen is None:
            return
        slot, person_id = chosen
        repo, pns = self.repo(), task.pns
        self.run_task(lambda: workflow_responses.reassign(repo, pns, slot, person_id), f"Changed who signs {task.label}")

    def _workflow_start(self, action, plan):
        """If this vault has workflows for the action, deal with it here (open the Workflow window, or finish a
        request that has all its sign-offs) and return True. Return False when it should just happen."""
        repo = self.repo()
        try:
            templates = workflow_store.templates_for(repo, action)
        except LitterboxError as e:
            messagebox.showerror("Litterbox", error_text.shorten(str(e)))
            return True
        pending = [pn for pn in plan.targets if self.rows_by_pn[pn].kind == "pending"]
        if not templates and not pending:
            return False
        if pending:
            if len(pending) != len(plan.targets):
                self._say("Some of these already have a request waiting. Select them separately.", "warn")
            else:
                self._finish_pending(action, pending)
            return True
        directory, me = self.identity.directory, self.identity.person
        if directory is None or me is None:
            self._say("Set up the team first (Team... > Set Up Team): sign-offs are done by people on it.", "warn")
            return True
        parts = [(pn, self.rows_by_pn[pn].name) for pn in plan.targets]
        chosen = request_dialog.WorkflowRequestDialog(self, action, parts, templates, directory, me.id).show()
        if not chosen:
            return True
        pns, label = list(plan.targets), workflow_templates.label_of(action)
        self.run_task(lambda: workflow_request.request(repo, pns, action, chosen["template"], chosen["assignments"],
                                               chosen["extras"], chosen["reason"]),
                      f"Started the {label} workflow on {len(pns)} part{'s' if len(pns) != 1 else ''}")
        return True

    def _finish_pending(self, action, pns):
        """The action's button on parts that already have a request: finish it if everyone has signed, else say
        what is missing."""
        repo, label = self.repo(), workflow_templates.label_of(action)
        rows = [self.rows_by_pn[pn] for pn in pns]
        other = next((r for r in rows if r.pending.get("action") != action), None)
        if other is not None:
            messagebox.showinfo(label, f"{other.pn} has a {workflow_templates.label_of(other.pending.get('action'))} request "
                                       "waiting for sign-offs. Open My Tasks to approve, reject or withdraw it.")
            return
        waiting = next((r for r in rows if not signoff_slots.is_complete(r.pending)), None)
        if waiting is not None:
            messagebox.showinfo(label, f"{waiting.pn} is still waiting for: " + ", ".join(
                signoff_slots.waiting_on(waiting.pending)) + ".\n\nOpen My Tasks to approve, reject or withdraw the "
                                                        "request.")
            return
        if messagebox.askokcancel(f"{label} {len(pns)} part{'s' if len(pns) != 1 else ''}",
                                  f"Everyone needed has signed. {label} now?"):
            self.run_task(lambda: workflow_signoff.complete_many(repo, pns), f"{label} done: {', '.join(map(str, pns))}")
