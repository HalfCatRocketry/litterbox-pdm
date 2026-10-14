"""
details_actions.py - Edit Details.
"""

from litterbox.gui.dialogs import edit_details_dialog
from litterbox.parts import part_details


class DetailsActions:
    """Edit Details. (a part of the main window, App)."""

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
