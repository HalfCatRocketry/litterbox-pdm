"""
cell_editing.py - editing a cell of the Import table in place (part number, name, description).
"""

import tkinter as tk

from litterbox.core import part_number
from litterbox.core.part_number import parse as parse_pn
from litterbox.gui import theme
from litterbox.gui.logic import import_table
from litterbox.gui.widgets import pn_editor


class CellEditing:
    """editing a cell of the Import table in place (part number, name, description). (part of the Import window)."""

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        column = self.EDIT_COLUMNS.get(self.tree.identify_column(event.x))
        iid = self.tree.identify_row(event.y)
        if not column or not iid or self._blocked():
            return
        self._end_edit()
        box = self.tree.bbox(iid, self.tree.identify_column(event.x))
        if not box:
            return
        x, y, w, h = box
        if column == "pn":
            base, variant = self._pn_parts(iid)
            editor = pn_editor.PnEditor(self.tree, self.org, base, variant, self._commit_edit, self._end_edit)
            editor.place(x, y, max(w, 200), h)
        else:
            editor = tk.Entry(self.tree, font=("Segoe UI", 10), bg="#1f1f1f", fg="#ffffff",
                              insertbackground="#ffffff", relief="flat", highlightthickness=1, highlightcolor=theme.ACCENT)
            editor.insert(0, self.tree.set(iid, column))
            editor.select_range(0, "end")
            editor.place(x=x, y=y, width=w, height=h)
            editor.focus_set()
            editor.bind("<Return>", lambda e: self._commit_edit())
            editor.bind("<Escape>", lambda e: self._end_edit())
            editor.bind("<FocusOut>", lambda e: self._commit_edit())
        self.editor = (editor, iid, column)
        return "break"

    def _pn_parts(self, iid):
        """The row's current part number as the two box texts ('00042', '001'), or empty boxes if unticked."""
        text = self.tree.set(iid, "pn")
        parsed = parse_pn(text) if text else None
        if not parsed:
            return "", ""
        return part_number.format_base(parsed.base), part_number.format_variant(parsed.variant)

    def _end_edit(self):
        if self.editor:
            editor, _iid, _column = self.editor
            self.editor = None
            try:
                editor.destroy()
            except tk.TclError:
                pass

    def _commit_edit(self):
        if not self.editor:
            return
        editor, iid, column = self.editor
        text = editor.get()
        self._end_edit()
        prepared = self.session.prepared
        index = next((n for n, e in enumerate(prepared.proposal.entries) if e.item.id == int(iid)), None)
        if column == "pn":
            problem = import_table.edit_import_pn(prepared, int(iid), text[0], text[1], repo=self.repo)
        else:
            problem = import_table.edit_import_cell(prepared, int(iid), column, text)
        self._say(problem, "warn" if problem else "normal")
        if column == "pn" and not problem:                    # an edited number is no longer known to be taken
            self.conflicts = [c for c in self.conflicts if c.index != index]
        self._rebuild()
