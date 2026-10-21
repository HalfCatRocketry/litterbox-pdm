"""
detail_pane.py - the details pane beside the parts list: it follows the highlighted part (the blue row), showing
its status, Details, History, what it uses and where it is used, and its BOM. The Uses, Where used and BOM tabs are
read in the background, only when one of them is showing. The pane can be hidden (its » button, or View > Details pane; a « at
the right of the toolbar brings it back) or popped out into a window of its own, whose tabs are read the same way.
"""

from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import status_icons
from litterbox.gui.logic import ui_scale
from litterbox.parts import bom_items
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.references import bom
from litterbox.references import reference_model
from litterbox.references import reference_queries
from litterbox.references import reference_reader

REFERENCE_TABS = ("Uses", "Where used")


class DetailPane:
    """the details pane (a part of the main window, App)."""

    pane_pn = None

    def details_shown(self):
        return str(self.detail_frame) in [str(p) for p in self.parts_screen.panes()]

    def set_details_pane(self, shown):
        """Show or hide the details pane, until Litterbox is closed: it always opens with the pane showing."""
        if shown == self.details_shown():
            return
        if shown:
            self.parts_screen.add(self.detail_frame, weight=0)
            self.pane_pn = None
            self._show_details()
        else:
            self.parts_screen.forget(self.detail_frame)
        self._show_pane_arrow()

    def _show_pane_arrow(self):
        """The « that brings the pane back shows at the right of the toolbar only while the pane is hidden."""
        button = getattr(self, "show_pane_button", None)
        if button is None:
            return
        if self.details_shown():
            button.grid_remove()
        else:
            button.grid()
        self._arrange_toolbar(self.toolbar.winfo_width())

    def _selection_changed(self):
        """The highlight moved (or the list was redrawn): update the buttons, and the pane a moment later, so
        running down the list with the arrow keys stays quick."""
        self._update_buttons()
        if getattr(self, "pane_view", None) is None:
            return
        job = getattr(self, "_pane_job", None)
        if job is not None:
            self.after_cancel(job)
        self._pane_job = self.after(120, self._show_details)

    def _pane_part(self):
        chosen = self.tree.selection()
        return parse_pn(chosen[0]) if len(chosen) == 1 else None

    def _show_details(self):
        self._pane_job = None
        if not self.details_shown():
            return
        pn = self._pane_part()
        row = self.rows_by_pn.get(pn) if pn is not None else None
        if row is None:
            self.pane_pn = None
            self.pane_icon.configure(image="")
            self.pane_title.configure(text="")
            self.pane_state.configure(text="Click a part to see its details.")
            self.pane_view.grid_remove()
            return
        self.pane_icon.configure(image=self.icons.status(row.kind, self._px(ui_scale.ICON + 4)))
        self.pane_title.configure(text=f"{row.pn.short}   {row.name}")
        busy = self.jobs.pending_parts().get(str(row.pn))
        label = status_icons.status_label(row.kind)
        state = row.state if row.state.lower().startswith(label.lower()) else f"{label}: {row.state}"
        self.pane_state.configure(text=state + (f"\nBusy: {busy}" if busy else ""))
        if pn == self.pane_pn and getattr(self, "_pane_rows", None) is self.rows:
            return                                          # the same part, and nothing reloaded: keep the tab as is
        self.pane_pn, self._pane_rows = pn, self.rows
        try:
            record = record_store.load(self.repo(), pn)
        except record_model.RegistryError as e:
            self.pane_state.configure(text=f"{state}\n\nIts record can't be read: {e}")
            self.pane_view.grid_remove()
            return
        self.pane_view.grid()
        self.pane_view.show(record, history_text.row_revisions(row))
        self._pane_refs_for = self._pane_bom_for = None     # show() emptied the Uses, Where used and BOM tabs
        if self.pane_view.current_tab() in REFERENCE_TABS:
            self._load_pane_references(pn)
        elif self.pane_view.current_tab() == "BOM":
            self._load_pane_bom()

    def _pane_tab_changed(self, name):
        if name in REFERENCE_TABS and self.pane_pn is not None:
            self._load_pane_references(self.pane_pn)
        elif name == "BOM" and self.pane_pn is not None:
            self._load_pane_bom()

    def _popout_tab_changed(self, window, pn, name):
        """A tab of a pop-out Details window (windows/history_window.py) was chosen: read what it shows, the first
        time it is shown."""
        if name in REFERENCE_TABS and "references" not in window.loaded:
            window.loaded.add("references")
            self._read_references_into(window.view, pn, window.winfo_exists)
        elif name == "BOM" and "bom" not in window.loaded:
            window.loaded.add("bom")
            self._read_bom_into(window.view, pn, window.winfo_exists)

    def _load_pane_bom(self):
        """Work out the BOM of the revision and the kind of list picked on the BOM tab, in the background."""
        pn = self.pane_pn
        if pn is None:
            return
        rev, mode = self.pane_view.bom_choice()
        if getattr(self, "_pane_bom_for", None) == (pn, rev, mode, id(self.rows)):
            return
        self._pane_bom_for = (pn, rev, mode, id(self.rows))
        self._read_bom_into(self.pane_view, pn, lambda: self.pane_pn == pn)

    def _read_bom_into(self, view, pn, wanted):
        """Work out the BOM of `pn` for the revision and kind of list picked on `view`'s BOM tab, in the background.
        wanted() says whether the view still shows that part once it is done."""
        rev, mode = view.bom_choice()
        view.show_bom(None, "Reading...")
        repo = self.repo()
        row = self.rows_by_pn.get(pn)
        mine = row is not None and row.kind == "mine"

        def load():
            try:
                records = reference_model.load_records(repo)
                record = records.get(pn)
                if record is None:
                    return None, f"There is no record for {pn}."
                found = bom.lines(records, pn, rev, mode)
                files = record_files.cad_files(repo, pn, rev)
                assembly = bom_items.takes_items(repo, record, files) or bool(reference_model.stems_of(record, rev))
                editable = mine and rev == record.revision and bom_items.takes_items(repo, record, files)
                removable = bom_text.removable(found) if mode != bom.FLAT else {}
                outdated = rev in record.references_outdated or rev in reference_queries.needs_update(repo, record)
                counts_outdated = rev in reference_queries.bom_needs_update(repo, record)
                if not (outdated or counts_outdated):
                    return bom_text.table(found, mode), bom_text.note(found, assembly), False, editable, removable
                installed = reference_reader.can_start_solidworks()
                note = bom_text.note(found, True, outdated, counts_outdated)
                if not installed:
                    note += " " + bom_text.update_button_text(False)
                return bom_text.table(found, mode), note, installed, editable, removable
            except LitterboxError as e:
                return None, f"Couldn't work out the BOM: {e}"

        def show(result):
            if wanted() and view.bom_choice() == (rev, mode):
                view.show_bom(*result)

        self.run_task(load, "", on_success=show, refresh=False, is_refresh=True, label="Reading the BOM")

    def _load_pane_references(self, pn):
        """Read what the part uses and where it is used, in the background, then fill the two tabs."""
        if getattr(self, "_pane_refs_for", None) == (pn, id(self.rows)):
            return
        self._pane_refs_for = (pn, id(self.rows))
        self._read_references_into(self.pane_view, pn, lambda: self.pane_pn == pn)

    def _read_references_into(self, view, pn, wanted):
        """Read what `pn` uses and where it is used, in the background, then fill `view`'s two tabs. wanted() says
        whether the view still shows that part once it is done."""
        view.show_references(None, None, "Reading...")
        repo = self.repo()

        def load():
            try:
                records = reference_model.load_records(repo)
                return reference_queries.uses(repo, pn, None, records), reference_queries.where_used(repo, pn, records), ""
            except LitterboxError as e:
                return None, None, str(e)

        def show(result):
            if not wanted():
                return                                  # another part was clicked meanwhile, or the window closed
            uses, used, problem = result
            view.show_references(uses, used, f"Couldn't read the references: {problem}" if problem else "")

        self.run_task(load, "", on_success=show, refresh=False, is_refresh=True, label="Reading references")

    def _pane_open(self, rev, drawing):
        if self.pane_pn is not None:
            self._open_revision(self.pane_pn, rev, drawing)
