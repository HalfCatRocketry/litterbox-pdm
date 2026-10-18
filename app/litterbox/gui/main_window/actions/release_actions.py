"""
release_actions.py - Release, Make COTS, Unrelease (reopen) and Void, with their confirmations.
"""

from tkinter import messagebox

from litterbox.gui.logic import action_rules
from litterbox.gui.logic import confirmations
from litterbox.gui.logic import job_text
from litterbox.parts import lifecycle
from litterbox.parts import planning


class ReleaseActions:
    """Release, Make COTS, Unrelease (reopen) and Void, with their confirmations. (a part of the main window, App)."""

    def release(self):
        plan = self._plan("release")
        if not plan:
            return
        if self._workflow_start("release", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        # Step 1: find out exactly what would be released. Step 2: ask. Step 3: do it.
        self.run_task(lambda: planning.release_plans(repo, pns), "Checked what a release would include",
                      on_success=lambda plans: self._confirm_release(repo, plans), refresh=False)

    def _confirm_release(self, repo, plans):
        good, bad = [p for p in plans if p.ok], [p for p in plans if not p.ok]
        if not good:
            messagebox.showwarning("Can't release yet", confirmations.plans_problem_text(bad, "released"))
            return
        if len(plans) == 1:
            title, text = f"Release {good[0].pn}", confirmations.release_confirm_text(good[0])
        else:
            title, text = f"Release {len(good)} parts", confirmations.release_many_confirm_text(good, bad)
        if not messagebox.askokcancel(title, text):
            return
        pns = [p.pn for p in good]
        skipped = [(p.pn, p.problems[0]) for p in bad]
        self.run_task(lambda: lifecycle.release_many(repo, pns), "",
                      on_success=lambda result: self._after_batch("release", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("release", len(pns)), parts=pns)

    def make_cots(self):
        plan = self._plan("make_cots")
        if not plan:
            return
        if self._workflow_start("make_cots", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        self.run_task(lambda: planning.make_cots_plans(repo, pns), "Checked whether they can be made COTS",
                      on_success=lambda plans: self._confirm_make_cots(repo, plans), refresh=False)

    def _confirm_make_cots(self, repo, plans):
        good, bad = [p for p in plans if p.ok], [p for p in plans if not p.ok]
        if not good:
            messagebox.showwarning("Can't make COTS yet", confirmations.plans_problem_text(bad, "made COTS"))
            return
        if len(plans) == 1:
            title = f"Make {good[0].pn} COTS"
            text = confirmations.make_cots_confirm_text(good[0].pn, good[0].name, good[0].files)
        else:
            title, text = f"Make {len(good)} parts COTS", confirmations.make_cots_many_confirm_text(good, bad)
        if not messagebox.askokcancel(title, text):
            return
        pns = [p.pn for p in good]
        skipped = [(p.pn, p.problems[0]) for p in bad]
        self.run_task(lambda: lifecycle.make_cots_many(repo, pns), "",
                      on_success=lambda result: self._after_batch("make_cots", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("make_cots", len(pns)), parts=pns)

    def reopen(self):
        plan = self._plan("reopen")
        if not plan:
            return
        if self._workflow_start("reopen", plan):
            return
        repo, pns = self.repo(), list(plan.targets)
        cots = [pn for pn in pns if self.rows_by_pn[pn].kind == "cots"]
        if cots and not messagebox.askyesno("Unrelease COTS part" + ("s" if len(cots) > 1 else ""),
                                            confirmations.reopen_cots_warning(cots)):
            return
        what = str(pns[0]) if len(pns) == 1 else f"these {len(pns)} parts"
        reason = self._ask_reason(f"Why {'is' if len(pns) == 1 else 'are'} {what} being unreleased?", "Unrelease")
        if reason:
            self.run_task(lambda: lifecycle.reopen_many(repo, pns, reason), "",
                          on_success=lambda result: self._after_batch("reopen", plan, result),
                          label=job_text.job_label("reopen", len(pns)), parts=pns)

    def void(self):
        plan = self._plan("void")
        if not plan:
            return
        if self._workflow_start("void", plan):
            return
        repo = self.repo()
        pns, skipped = [], list(plan.skipped)
        for pn in plan.targets:
            problem = confirmations.void_problem(self.rows_by_pn[pn])
            if problem:
                skipped.append((pn, problem))
            else:
                pns.append(pn)
        if not pns:
            messagebox.showwarning("Can't void", "\n\n".join(why for _pn, why in skipped))
            return
        what = str(pns[0]) if len(pns) == 1 else f"these {len(pns)} parts"
        reason = self._ask_reason(f"Why {'is' if len(pns) == 1 else 'are'} {what} being voided?", "Void")
        if not reason:
            return
        if not messagebox.askyesno(
                "Void part" + ("s" if len(pns) != 1 else ""),
                f"Void {pns[0]}?\n\nIts number will never be used again, and it can't be checked out."
                if len(pns) == 1 else confirmations.void_many_confirm_text(pns)):
            return
        self.run_task(lambda: lifecycle.void_many(repo, pns, reason), "",
                      on_success=lambda result: self._after_batch("void", action_rules.ActionPlan(pns, skipped), result),
                      label=job_text.job_label("void", len(pns)), parts=pns)
