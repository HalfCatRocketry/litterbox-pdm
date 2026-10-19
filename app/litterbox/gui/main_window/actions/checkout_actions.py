"""
checkout_actions.py - Check Out, Undo Checkout and Break Checkout.
"""

from tkinter import messagebox

from litterbox.gui.logic import checkin_text
from litterbox.parts import break_checkout as breaking
from litterbox.parts import checkout
from litterbox.parts import undoing


class CheckoutActions:
    """Check Out, Undo Checkout and Break Checkout. (a part of the main window, App)."""

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
        if plan:
            self._run_batch("checkout", plan, checkout.checkout_many)

    def undo_checkout(self):
        plan = self._plan("undo")
        if not plan:
            return
        if not messagebox.askyesno("Undo checkout", checkin_text.undo_prompt(plan.targets)):
            return
        self._run_batch("undo", plan, undoing.undo_checkout_many)
