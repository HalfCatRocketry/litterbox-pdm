"""
parts_list.py - the parts list: loading it (refresh, Get Latest), showing and filtering rows, ticks and
selection, and which buttons are usable.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from litterbox import diagnostics
from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import job_text
from litterbox.gui.logic import list_view
from litterbox.parts import get_latest
from litterbox.parts import part_status
from litterbox.team import team_identity


class PartsList:
    """the parts list: loading it (refresh, Get Latest), showing and filtering rows, ticks and (a part of the main window, App)."""

    def _update_buttons(self):
        """Grey out the buttons that can't be used on the current selection: a button is lit only if every part it
        would act on is one it can be used on, and has no job in progress."""
        if not getattr(self, "action_buttons", None):
            return
        tree = self.tree
        highlighted = [parse_pn(iid) for iid in tree.selection()]
        states = action_rules.button_states(self._ticked_pns(), highlighted, self.rows_by_pn, self.jobs.pending_parts())
        for text, button in self.action_buttons.items():
            button.configure(state="normal" if states.get(text) else "disabled")
        deselect = getattr(self, "deselect_button", None)
        if deselect is not None:
            deselect.configure(state="normal" if self.ticked or highlighted else "disabled")

    def _deselect_all(self):
        """Clear every box (and the highlight)."""
        self._set_ticks(list(self.tree.get_children()) + list(self.ticked), False)
        self.tree.selection_set(*[])
        self._update_buttons()

    def _ticked_pns(self):
        """The ticked parts that are shown in the list right now (a tick on a filtered-out part is ignored)."""
        ticked = getattr(self, "ticked", set())
        return [parse_pn(iid) for iid in self.tree.get_children() if iid in ticked]

    def _selected_pns(self, action=None):
        """The parts an action applies to: see action_rules.choose_targets."""
        highlighted = [parse_pn(iid) for iid in self.tree.selection()]
        if action is None:
            return highlighted
        return action_rules.choose_targets(action, self._ticked_pns(), highlighted)

    def _on_tree_click(self, event):
        """A click in the tick column flips that row's box and leaves the highlight alone."""
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return None
        iid = self.tree.identify_row(event.y)
        if iid:
            shown = list(self.tree.get_children())
            anchor = getattr(self, "last_tick", None)
            if list_view.shift_held(event) and anchor in shown:   # Shift: tick everything from the last click to here
                self._set_ticks(list_view.range_between(shown, anchor, iid), anchor in self.ticked)
            else:
                self._set_ticks([iid], iid not in self.ticked)
            self.last_tick = iid
        return "break"

    def _tick_highlighted(self, event=None):
        chosen = list(self.tree.selection())
        if chosen:
            self._set_ticks(chosen, not all(iid in self.ticked for iid in chosen))
        return "break"

    def _toggle_all_ticks(self):
        shown = list(self.tree.get_children())
        self._set_ticks(shown, not (shown and all(iid in self.ticked for iid in shown)))

    def _set_ticks(self, iids, on):
        for iid in iids:
            (self.ticked.add if on else self.ticked.discard)(iid)
            if not self.tree.exists(iid):
                continue
            self.tree.set(iid, "tick", list_view.TICK_ON if on else list_view.TICK_OFF)
            kinds = [t for t in self.tree.item(iid, "tags") if t != "ticked"]
            self.tree.item(iid, tags=list_view.row_tags(kinds[0], on) if kinds else ())
        shown = self.tree.get_children()
        self.tree.heading("tick", text=list_view.TICK_ON if shown and all(i in self.ticked for i in shown) else list_view.TICK_OFF)
        self._say(list_view.tick_text(len(self._ticked_pns())))
        self._update_buttons()

    def _plan(self, action):
        """Work out what the selected parts allow. Shows the reason and returns None if nothing can be done."""
        allowed, why = self.identity.allows(action)
        if not allowed:
            self._say(why, "warn")
            return None
        plan = action_rules.plan_action(action, self._selected_pns(action), self.rows_by_pn, self.jobs.pending_parts())
        if plan.message:
            self._say(plan.message, "warn")
            return None
        return plan

    def refresh(self):
        repo = self.repo()
        def work():
            def find_out_who():
                try:
                    return team_identity.current(repo)
                except LitterboxError as e:           # a damaged team file must not hide the parts
                    return team_identity.Identity(team_identity.UNVERIFIED, detail=str(e).splitlines()[0])

            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=2) as pool:      # the list and "who am I" don't depend on each other
                who_job = pool.submit(find_out_who)
                rows = part_status.get_status(repo)
                who = who_job.result()
            if diagnostics.DEBUG:
                diagnostics.LOG(f"Refreshed the list in {time.monotonic() - started:.1f}s")
            return rows, who

        def show(result):
            rows, who = result
            self.identity = who
            self._show_identity()
            self._show_rows(rows)

        self.run_task(work, "Up to date", on_success=show, refresh=False, is_refresh=True, label="Refreshing the list",
                      kind="refresh")

    def _show_rows(self, rows):
        self.rows = rows
        self.rows_by_pn = {row.pn: row for row in rows}
        self._refresh_tasks()
        shown = self._render()
        if self.pending_select:
            if self.tree.exists(self.pending_select):
                self.tree.selection_set(self.pending_select)
                self.tree.see(self.pending_select)
            self.pending_select = None
        if not rows:
            self._say("No parts found. Check that this is your vault folder (it should contain a PN-logs folder).", "warn")
            return
        count = f"{shown} of {len(rows)} parts shown" if shown != len(rows) else f"{len(rows)} parts"
        ticked = len(self._ticked_pns())
        count += f"   |   {ticked} ticked" if ticked else ""
        self._say((self.note + "   |   " if self.note else "") + count)

    def _render(self):
        """Redraw the list using the search box and filters. Returns how many rows are shown."""
        rows = list_view.filter_rows(self.rows, self.search.get(), self.view.get(), bool(self.void_box.get()))
        self.ticked &= {str(row.pn) for row in self.rows}                     # parts that no longer exist lose their tick
        if not self.void_box.get():                                           # so do void parts that are now hidden
            self.ticked -= {str(row.pn) for row in self.rows if row.kind == "void"}
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        busy = self.jobs.pending_parts()                                    # parts with a job queued or running
        self._shown_pending = dict(busy)
        for row in rows:
            mark = busy.get(str(row.pn))
            self.tree.insert("", "end", iid=str(row.pn),
                             tags=list_view.row_tags(row.kind, str(row.pn) in self.ticked) + (("busy",) if mark else ()),
                             values=(
                list_view.TICK_ON if str(row.pn) in self.ticked else list_view.TICK_OFF,
                row.pn.short, row.name, row.description, "Yes" if row.cots else "", row.revision,
                job_text.busy_state_text(row.state, mark) if mark else row.state,
                list_view.file_types(row.files)))
        keep = [str(row.pn) for row in rows if str(row.pn) in previous]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self._update_buttons()
        return len(rows)

    def get_latest(self):
        repo = self.repo()
        self.run_task(lambda: get_latest.get_latest(repo), "Downloaded the latest changes", label="Getting the latest",
                      on_success=lambda changed: self._warn_open_files(changed))
