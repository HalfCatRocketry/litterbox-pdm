"""
details_actions.py - Edit Details and Purchasing Info.
"""

from tkinter import messagebox

from litterbox.gui.dialogs import edit_details_dialog
from litterbox.gui.dialogs import purchasing_dialog
from litterbox.gui.logic import purchasing_text
from litterbox.parts import part_details
from litterbox.parts import purchasing
from litterbox.records import record_model
from litterbox.records import record_store


class DetailsActions:
    """Edit Details and Purchasing Info. (a part of the main window, App)."""

    def edit_purchasing(self):
        plan = self._plan("purchasing")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            messagebox.showerror("Litterbox", str(e), parent=self)
            return
        mine = self.rows_by_pn[pn].kind == "mine"
        note = ("You have it checked out: the change goes up with your next Save Progress or Check In." if mine else
                "It is uploaded as soon as you save. No check-out is needed.")
        fields = purchasing_dialog.PurchasingDialog(self, pn, record.purchasing, note).show()
        if fields is None:
            self._say("Nothing was changed.")
            return
        self.run_task(lambda: purchasing.edit_purchasing(repo, pn, fields), "",
                      on_success=lambda outcome: self._purchasing_done(pn, outcome),
                      label=f"Saving the purchasing info of {pn.short}", parts=[pn])

    def _purchasing_done(self, pn, outcome):
        self.note = purchasing_text.done_text(pn, outcome)          # kept on the status line after the refresh
        self._say(self.note)

    def edit_details(self):
        plan = self._plan("edit")
        if not plan:
            return
        repo, pn = self.repo(), plan.targets[0]
        row = self.rows_by_pn[pn]
        result = edit_details_dialog.EditDetailsDialog(self, pn, row.name, row.description).show()
        if result is None:
            self._say("Nothing was changed.")
            return
        name, description = result
        self.run_task(lambda: part_details.edit_details(repo, pn, name, description),
                      f"Updated the details of {pn}. Save Progress or Check In to upload them.")
