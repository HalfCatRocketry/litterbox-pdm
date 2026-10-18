"""
checkout_actions.py - Check Out and Undo Checkout.
"""

from tkinter import messagebox

from litterbox.gui.logic import checkin_text
from litterbox.parts import checkout
from litterbox.parts import undoing


class CheckoutActions:
    """Check Out and Undo Checkout. (a part of the main window, App)."""

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
