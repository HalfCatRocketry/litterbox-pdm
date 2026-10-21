"""
details_actions.py - Edit Details, Purchasing Info, and the BOM lines added by hand (the BOM tab's Add item...
and Remove).
"""

from tkinter import messagebox

from litterbox.gui.dialogs import bom_item_dialog
from litterbox.gui.dialogs import edit_details_dialog
from litterbox.gui.dialogs import purchasing_dialog
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import confirmations
from litterbox.gui.logic import purchasing_text
from litterbox.parts import bom_items
from litterbox.parts import part_details
from litterbox.parts import purchasing
from litterbox.records import record_model
from litterbox.records import record_store


class DetailsActions:
    """Edit Details, Purchasing Info and BOM lines added by hand. (a part of the main window, App)."""

    def add_bom_item(self, pn, then=None):
        """Add item... on the BOM tab of `pn` (an assembly you have checked out). `then()` re-reads the tab."""
        row = self.rows_by_pn.get(pn)
        if row is None:
            return
        note = ("A non-CAD assembly lists any part: its BOM is these lines." if row.noncad else
                "Only non-CAD parts (paint, glue, stock) are added by hand: the CAD parts come from the model.")
        choices = bom_text.item_choices(list(self.rows_by_pn.values()), row)
        answer = bom_item_dialog.BomItemDialog(self, pn, choices, note).show()
        if answer is None:
            return
        repo, (item, quantity) = self.repo(), answer
        self.run_task(lambda: bom_items.set_item(repo, pn, item, quantity),
                      f"Added {item} to the BOM of {pn}. Save Progress or Check In to upload it.",
                      on_success=lambda _stem: self._bom_edited(then), refresh=False,
                      label=f"Changing the BOM of {pn.short}", parts=[pn])

    def remove_bom_item(self, pn, stem, then=None):
        if not messagebox.askyesno("Remove from BOM", f"Take {stem} off the BOM of {pn}?", parent=self):
            return
        repo = self.repo()
        self.run_task(lambda: bom_items.remove_item(repo, pn, stem),
                      f"Took {stem} off the BOM of {pn}. Save Progress or Check In to upload it.",
                      on_success=lambda _none: self._bom_edited(then), refresh=False,
                      label=f"Changing the BOM of {pn.short}", parts=[pn])

    def _bom_edited(self, then):
        self._pane_bom_for = None                   # read the pane's BOM tab again
        if then is not None:
            then()
        elif getattr(self, "pane_pn", None) is not None:
            self._load_pane_bom()

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
        kind = record_model.KIND_NONCAD if row.noncad else record_model.KIND_CAD
        result = edit_details_dialog.EditDetailsDialog(self, pn, row.name, row.description, kind,
                                                       confirmations.kind_note(row)).show()
        if result is None:
            self._say("Nothing was changed.")
            return
        name, description, kind = result
        self.run_task(lambda: part_details.edit_details(repo, pn, name, description, kind),
                      f"Updated the details of {pn}. Save Progress or Check In to upload them.")
