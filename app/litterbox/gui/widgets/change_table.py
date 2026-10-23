"""
change_table.py - ChangeTable: the parts table of the Workflow, Review and Release/Void windows. Part, Name, Rev
('A → B'), and for each part that takes them, Form, Fit and Function tick boxes and a Dispo drop-down (what to do with
the earlier revision's parts). A part that doesn't take them (a first release, a document) shows dashes. Clicking a
box ticks it; clicking Dispo opens its menu. Read-only, it only shows them. ask_changes(False) hides Form, Fit, Function
and Dispo (a workflow that needs no ECO doesn't ask them). The words are gui/logic/change_text.py's.
"""

import tkinter.font as tkfont
from tkinter import ttk

from litterbox.gui.logic import change_text
from litterbox.gui.widgets import menu_bar

PAD = 24                        # room either side of a column's text
LEFT = ("pn", "name", "rev", "dispo")


class ChangeTable:
    """Build it into `parent` and grid its `tree`. `parts` is [(PN, name, revision, released revision)];
    `changes` is {part number text: {"changed", "disposition"}}, kept up to date as boxes are clicked."""

    def __init__(self, parent, action, parts=(), changes=None, read_only=False, height=4, on_change=None):
        self.action, self.read_only, self.on_change = action, read_only, on_change
        self.parts, self.changes, self.asking = [], dict(changes or {}), True
        self.tree = ttk.Treeview(parent, columns=[key for key, _title in change_text.COLUMNS], show="headings",
                                 height=height, selectmode="extended")
        for key, title in change_text.COLUMNS:
            self.tree.heading(key, text=title, anchor="w" if key in LEFT else "center")
            self.tree.column(key, width=change_text.WIDTHS.get(key, 200), stretch=key == "name",
                             anchor="w" if key in LEFT else "center")
        if not read_only:
            self.tree.bind("<Button-1>", self._click)
        self.set_parts(parts)

    def set_parts(self, parts):
        """Show these parts. A part already shown keeps what was ticked for it."""
        self.parts = [tuple(p) for p in parts]
        keep = {str(p[0]) for p in self.parts}
        self.changes = {pn: change for pn, change in self.changes.items() if pn in keep}
        self.tree.delete(*self.tree.get_children())
        for part in self.parts:
            self.tree.insert("", "end", iid=str(part[0]), values=self._values(part))
        self._fit_columns()

    def _values(self, part):
        pn, name, revision, released = part
        asked = change_text.asks(pn, self.action, revision, released)
        values = change_text.cells(pn, name, revision, self.earlier(part), self.changes.get(str(pn)), asked)
        if asked[1] and not self.read_only:
            values[-1] += "  ▾"
        return values

    def earlier(self, part):
        """The revision released before the one this part goes through ('' for none), for 'A → B'."""
        _pn, _name, revision, released = part
        if change_text.asks(part[0], self.action, revision, released) == (False, True):
            return ""                                   # a void: the revision is the one disposed of
        return released if released and released != revision else ""

    def ask_changes(self, asking):
        """Show Form, Fit, Function and Dispo (True) or hide them; hidden, nothing is asked (missing() is empty and
        result() None)."""
        self.asking = bool(asking)
        keys = [key for key, _title in change_text.COLUMNS]
        self.tree.configure(displaycolumns=keys if self.asking else [k for k in keys if k in change_text.ALWAYS])

    def _fit_columns(self):
        """Every column but Name wide enough for its heading and its widest cell, at any display scaling: the Part
        column for however many digits the org uses, Form, Fit and Function for their bold headings."""
        try:
            style = ttk.Style()
            body = tkfont.Font(font=style.lookup("Treeview", "font") or "TkDefaultFont")
            heading = tkfont.Font(font=style.lookup("Treeview.Heading", "font") or "TkHeadingFont")
            rows = [self.tree.item(iid, "values") for iid in self.tree.get_children()]
            for index, (key, title) in enumerate(change_text.COLUMNS):
                if key == "name":
                    continue
                widest = max([body.measure(str(row[index])) for row in rows if index < len(row)]
                             + [heading.measure(title)])
                width = max(widest + PAD, change_text.WIDTHS.get(key, 0))
                self.tree.column(key, width=width, minwidth=width)
        except Exception:                               # no font yet (a window being closed): keep the widths
            return

    def _part(self, pn):
        return next((p for p in self.parts if str(p[0]) == str(pn)), None)

    def _redraw(self, pn):
        part = self._part(pn)
        if part is not None:
            self.tree.item(str(pn), values=self._values(part))
            self._fit_columns()
        if self.on_change:
            self.on_change()

    def toggle(self, pn, key):
        """Tick or untick form, fit or function for a part, if it takes them."""
        part = self._part(pn)
        if part is None or not change_text.asks(part[0], self.action, part[2], part[3])[0]:
            return
        self.changes[str(pn)] = change_text.toggled(self.changes.get(str(pn)), key)
        self._redraw(pn)

    def choose(self, pn, disposition):
        """Set a part's disposition, if it takes one."""
        part = self._part(pn)
        if part is None or not change_text.asks(part[0], self.action, part[2], part[3])[1]:
            return
        self.changes[str(pn)] = change_text.with_disposition(self.changes.get(str(pn)), disposition)
        self._redraw(pn)

    def _click(self, event):
        pn = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not pn or not column:
            return
        key = self.tree.column(column, "id")
        if key in ("form", "fit", "function"):
            self.toggle(pn, key)
        elif key == "dispo":
            self._dispo_menu(pn, event)

    def _dispo_menu(self, pn, event):
        part = self._part(pn)
        if part is None or not change_text.asks(part[0], self.action, part[2], part[3])[1]:
            return
        menu = menu_bar.dark_menu(self.tree)
        for label, key in change_text.disposition_choices():
            menu.add_command(label=label, command=lambda key=key: self.choose(pn, key))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def selection(self):
        return self.tree.selection()

    def missing(self):
        """The parts (text) still without a disposition that needs one."""
        if not self.asking:
            return []
        return change_text.missing_dispositions([(p[0], p[2], p[3]) for p in self.parts], self.action, self.changes)

    def result(self):
        """{part number text: change} for the parts that take one; None when nothing is asked (ask_changes(False))."""
        if not self.asking:
            return None
        return change_text.kept([(p[0], p[2], p[3]) for p in self.parts], self.action, self.changes)
