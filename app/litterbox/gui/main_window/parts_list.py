"""
parts_list.py - the parts list: loading it (refresh, Get Latest), showing and filtering rows, the tick boxes and
status icons in its first column, cutting long text to the column width, the Columns menu, and which buttons are
usable.
"""

import time
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox

from litterbox import diagnostics
from litterbox.core.part_number import parse as parse_pn
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.gui import scaling
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import download_text
from litterbox.gui.logic import job_text
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import list_view
from litterbox.gui.logic import status_icons
from litterbox.gui.logic import text_fit
from litterbox.gui.logic import ui_scale
from litterbox.gui.widgets import table_sorting
from litterbox.parts import downloads
from litterbox.parts import get_latest
from litterbox.parts import part_status
from litterbox.team import team_identity
from litterbox.user import settings

FIRST_COLUMN = "#0"             # the tick box and status icon


class PartsList:
    """the parts list (a part of the main window, App)."""

    # -- columns -----------------------------------------------------------------------------------------------
    def _set_up_columns(self):
        """Show the chosen columns at their widths for this display scaling, with sortable headings."""
        tree = self.tree
        keys = list(self.list_keys)
        tree.configure(displaycolumns=keys)
        icon = self._icon_size()
        tree.column(FIRST_COLUMN, width=status_icons.strip_width(icon) + self._px(14), minwidth=self._px(40),
                    stretch=False, anchor="w")
        tree.heading(FIRST_COLUMN, image=self.icons.tick(icon, False), command=self._toggle_all_ticks, anchor="w")
        for column in list_columns.COLUMNS:
            tree.column(column.key, width=self._px(column.width), minwidth=self._px(36), anchor="w",
                        stretch=column.stretch)
        self.sorter = table_sorting.TableSorter(tree, [(c.key, c.title) for c in list_columns.COLUMNS])

    def _icon_size(self):
        return self._px(ui_scale.ICON)

    def _fill_columns_menu(self, menu):
        """The Columns menu: a tick for each column that is shown."""
        for column in list_columns.COLUMNS:
            menu.add_checkbutton(label=column.title, onvalue=True, offvalue=False,
                                 state="disabled" if column.key == "pn" else "normal",
                                 variable=self._menu_flag(column.key in self.list_keys),
                                 command=lambda key=column.key: self.toggle_column(key))

    def toggle_column(self, key):
        self.list_keys = list_columns.toggled(self.list_keys, key)
        self.settings["list_columns"] = list(self.list_keys)
        settings.save(self.settings)
        self._set_up_columns()
        choices = list_columns.search_choices(self.list_keys)
        self.search_in_menu.configure(values=choices)
        if self.search_in.get() not in choices:
            self.search_in.set(list_columns.ALL_COLUMNS)
        self._render()

    # -- fitting long text ---------------------------------------------------------------------------------------
    def _measure(self, text):
        cache = self.__dict__.setdefault("_widths", {})
        width = cache.get(text)
        if width is None:
            font = self.__dict__.get("_list_font")
            if font is None:
                font = self._list_font = tkfont.Font(root=self, font=scaling.font(ui_scale.TABLE_FONT, self.scale))
            width = cache[text] = font.measure(text)
        return width

    def _cell_values(self, row):
        """The texts a row shows, one per column (long ones cut to the column's width)."""
        values = []
        for column in list_columns.COLUMNS:
            text = column.text(row)
            if column.fit and column.key in self.list_keys:
                try:
                    width = int(self.tree.column(column.key, "width")) - self._px(14)
                    text = text_fit.fit(text, width, self._measure)
                except Exception:
                    text = text_fit.one_line(text)
            values.append(text)
        return values

    def _refit_soon(self):
        if getattr(self, "_refit_job", None) is None:
            self._refit_job = self.after(150, self._refit)

    def _refit(self):
        """After a column or the window changed size: cut the long texts again."""
        self._refit_job = None
        widths = tuple(self.tree.column(c.key, "width") for c in list_columns.COLUMNS if c.fit)
        if widths == getattr(self, "_fitted_widths", None):
            return
        self._fitted_widths = widths
        for iid in self.tree.get_children():
            row = self.rows_by_pn.get(parse_pn(iid))
            if row is not None:
                self.tree.item(iid, values=self._cell_values(row))

    def _forget_measures(self):
        """The font changed size: measure again."""
        self.__dict__.pop("_list_font", None)
        self.__dict__.pop("_widths", None)
        self._fitted_widths = None

    def _cell_tooltip(self, iid, column):
        """The note when the mouse rests on a cell: what the icon means, or the full text of a cut-off cell."""
        row = self.rows_by_pn.get(parse_pn(iid)) if iid else None
        if row is None:
            return ""
        if column == FIRST_COLUMN:
            title = status_icons.status_label(row.kind)
            busy = self.jobs.pending_parts().get(str(row.pn))
            lines = [row.state if row.state.lower().startswith(title.lower()) else f"{title}: {row.state}"]
            if busy:
                lines.append(f"Busy: {busy}")
            return "\n".join(lines)
        try:
            key = self.tree.column(column, "id")
        except Exception:
            return ""
        spec = list_columns.BY_KEY.get(key)
        if spec is None or not spec.fit:
            return ""
        full, shown = text_fit.one_line(spec.text(row)), self.tree.set(iid, key)
        return full if full != shown else ""

    # -- buttons and ticks ------------------------------------------------------------------------------------------
    def _update_buttons(self):
        """Grey out the buttons that can't be used on the current selection: a button is lit only if every part it
        would act on is one it can be used on, and has no job in progress."""
        if not getattr(self, "action_buttons", None):
            return
        highlighted = [parse_pn(iid) for iid in self.tree.selection()]
        states = action_rules.button_states(self._ticked_pns(), highlighted, self.rows_by_pn, self.jobs.pending_parts())
        for text, button in self.action_buttons.items():
            button.configure(state="normal" if states.get(text) else "disabled")
        deselect = getattr(self, "deselect_button", None)
        if deselect is not None:
            deselect.configure(state="normal" if self.ticked or highlighted else "disabled")
        acting = getattr(self, "acting_label", None)
        if acting is not None:
            count = len(self._ticked_pns())
            acting.configure(text=f"Acting on: {count} ticked" if count else "Nothing ticked")

    def _why_greyed(self, text):
        """The tooltip of a toolbar button or menu entry: why it can't be used now ("" if it can)."""
        action = action_rules.BUTTON_ACTIONS.get(text)
        if action is None:
            return ""
        highlighted = [parse_pn(iid) for iid in self.tree.selection()]
        return action_rules.why_not(action, self._ticked_pns(), highlighted, self.rows_by_pn, self.jobs.pending_parts())

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
        """A click on a row's tick box flips it and leaves the highlight alone."""
        if self.tree.identify_region(event.x, event.y) not in ("tree", "cell") \
                or self.tree.identify_column(event.x) != FIRST_COLUMN:
            return None
        if event.x > self._px(8) + self._icon_size() + self._px(4):        # the status icon: just a click on the row
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

    def _row_image(self, row, ticked, busy):
        return self.icons.row(self._icon_size(), ticked, row.kind, bool(busy),
                              bool(getattr(row, "not_downloaded", False)) and row.kind != "void")

    def _set_ticks(self, iids, on):
        busy = self.jobs.pending_parts() if getattr(self, "jobs", None) is not None else {}
        for iid in iids:
            (self.ticked.add if on else self.ticked.discard)(iid)
            if not self.tree.exists(iid):
                continue
            kinds = [t for t in self.tree.item(iid, "tags") if t not in ("ticked", "busy")]
            extra = ("busy",) if iid in busy else ()
            self.tree.item(iid, tags=(list_view.row_tags(kinds[0], on) if kinds else ()) + extra)
            row = self.rows_by_pn.get(parse_pn(iid)) if getattr(self, "rows_by_pn", None) else None
            if row is not None:
                self.tree.item(iid, image=self._row_image(row, on, iid in busy))
        shown = self.tree.get_children()
        self.tree.heading(FIRST_COLUMN, image=self.icons.tick(self._icon_size(),
                                                              bool(shown) and all(i in self.ticked for i in shown)))
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

    # -- loading -------------------------------------------------------------------------------------------------
    def refresh(self):
        repo = self.repo()
        on_demand = settings.downloads_on_demand(getattr(self, "settings", {}))
        def work():
            def find_out_who():
                try:
                    return team_identity.current(repo)
                except LitterboxError as e:           # a damaged team file must not hide the parts
                    return team_identity.Identity(team_identity.UNVERIFIED, detail=str(e).splitlines()[0])

            started = time.monotonic()
            self._use_download_setting(repo, on_demand)
            with ThreadPoolExecutor(max_workers=3) as pool:      # the list, "who am I" and the server are separate
                who_job = pool.submit(find_out_who)
                behind_job = pool.submit(remote.commits_behind, repo)
                rows = part_status.get_status(repo)
                who, behind = who_job.result(), behind_job.result()
            if diagnostics.DEBUG:
                diagnostics.LOG(f"Refreshed the list in {time.monotonic() - started:.1f}s")
            return rows, who, behind

        def show(result):
            rows, who, behind = result
            self.identity = who
            self._show_identity()
            self._show_behind(behind)
            self._show_rows(rows)

        self.run_task(work, "Up to date", on_success=show, refresh=False, is_refresh=True, label="Refreshing the list",
                      kind="refresh")

    def _use_download_setting(self, repo, on_demand):
        """Once per vault and session: make the vault download on demand, or everything, as settings.yaml says
        (see parts/downloads.py). Runs in the background, with the refresh. A problem is logged, never fatal."""
        done = self.__dict__.setdefault("_download_setting_used", set())
        if repo in done:
            return
        done.add(repo)
        try:
            if downloads.apply_mode(repo, on_demand):
                diagnostics.LOG("This vault now downloads " + ("CAD files when they are used." if on_demand
                                                               else "every CAD file."))
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not set how this vault downloads files. {e}")

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
        self._update_counts()
        self._selection_changed()
        if not rows:
            self._say("No parts found. Check that this is your vault folder (it should contain a PN-logs folder).", "warn")
            return
        count = f"{shown} of {len(rows)} parts shown" if shown != len(rows) else f"{len(rows)} parts"
        ticked = len(self._ticked_pns())
        count += f"   |   {ticked} ticked" if ticked else ""
        self._say((self.note + "   |   " if self.note else "") + count)

    def _render(self):
        """Redraw the list using the search box, the view and the 'search in' column. Returns how many rows show."""
        choice = self.search_in.get() if getattr(self, "search_in", None) is not None else list_columns.ALL_COLUMNS
        keys = list_columns.search_keys(choice)
        rows = list_view.filter_rows(self.rows, self.search.get(), self.view.get(),
                                     values=lambda row: list_columns.search_values(row, keys))
        self.ticked &= {str(row.pn) for row in self.rows}                     # parts that no longer exist lose their tick
        if self.view.get() != "Void":                                         # so do void parts that are now hidden
            self.ticked -= {str(row.pn) for row in self.rows if row.kind == "void"}
        self.rows_by_pn = {row.pn: row for row in self.rows}
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        busy = self.jobs.pending_parts()                                    # parts with a job queued or running
        self._shown_pending = dict(busy)
        for row in rows:
            iid, mark = str(row.pn), busy.get(str(row.pn))
            values = self._cell_values(row)
            if mark:
                values[[c.key for c in list_columns.COLUMNS].index("state")] = job_text.busy_state_text(row.state, mark)
            self.tree.insert("", "end", iid=iid, text="", image=self._row_image(row, iid in self.ticked, mark),
                             tags=list_view.row_tags(row.kind, iid in self.ticked) + (("busy",) if mark else ()),
                             values=values)
        keep = [str(row.pn) for row in rows if str(row.pn) in previous]
        if keep:
            self.tree.selection_set(*keep)
        self.sorter.apply()
        self._update_buttons()
        return len(rows)

    def get_latest(self):
        repo = self.repo()
        others = [f for row in getattr(self, "rows", []) if row.kind != "mine" for f in row.files]
        if not self._closed_in_solidworks(others):         # a download may replace a file open in SolidWorks
            return
        self.run_task(lambda: get_latest.get_latest(repo), "Downloaded the latest changes", label="Getting the latest",
                      on_success=lambda changed: self._warn_open_files(changed))

    def download_all(self):
        """Download every CAD file of the vault, not just the ones you use. Get Latest then keeps them all current."""
        if not messagebox.askyesno("Download All", download_text.DOWNLOAD_ALL_QUESTION, parent=self):
            return
        repo = self.repo()
        self.run_task(lambda: downloads.download_all(repo), "Downloaded every CAD file", label="Downloading everything")
