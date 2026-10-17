"""
tooltip.py - the small note that appears when the mouse rests on something: Tooltip for a widget (a greyed-out
button says why it is greyed out) and TableTooltip for a table's cells (the full text of a cut-off cell, or what a
status icon means). The text can be worked out at the moment it is shown.
"""

import tkinter as tk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import ui_scale

DELAY_MS = 450


class _Note:
    """The note window itself: one at a time per owner."""

    def __init__(self, owner):
        self.owner, self.window, self.timer = owner, None, None

    def schedule(self, text_for, x=None, y=None):
        self.cancel()
        try:
            self.timer = self.owner.after(DELAY_MS, lambda: self.show(text_for, x, y))
        except Exception:
            self.timer = None

    def show(self, text_for, x=None, y=None):
        self.timer = None
        try:
            text = text_for() if callable(text_for) else text_for
        except Exception:
            text = ""
        self.hide()
        if not text:
            return
        try:
            scale = scaling.scale_of(self.owner)
            window = tk.Toplevel(self.owner)
            window.wm_overrideredirect(True)
            window.attributes("-topmost", True)
            tk.Label(window, text=text, justify="left", bg="#3a3a3a", fg=theme.TEXT, bd=0,
                     font=scaling.font(13, scale), wraplength=ui_scale.px(380, scale),
                     padx=ui_scale.px(8, scale), pady=ui_scale.px(5, scale)).pack()
            if x is None:
                x, y = self.owner.winfo_pointerx(), self.owner.winfo_pointery()
            window.update_idletasks()
            gap = ui_scale.px(16, scale)
            x = min(x + gap // 2, window.winfo_screenwidth() - window.winfo_reqwidth() - 4)
            y = y + gap
            if y + window.winfo_reqheight() > window.winfo_screenheight():
                y = y - 2 * gap - window.winfo_reqheight()
            window.wm_geometry(f"+{max(x, 0)}+{max(y, 0)}")
            self.window = window
        except Exception:
            self.window = None

    def cancel(self):
        if self.timer is not None:
            try:
                self.owner.after_cancel(self.timer)
            except Exception:
                pass
            self.timer = None

    def hide(self):
        self.cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None


class Tooltip:
    """Show `text` (a string, or a function giving one; "" shows nothing) when the mouse rests on `widget`."""

    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.note = _Note(widget)
        for sequence, handler in (("<Enter>", self._enter), ("<Leave>", self._leave), ("<ButtonPress>", self._leave)):
            try:
                widget.bind(sequence, handler, add="+")
            except Exception:
                pass

    def _enter(self, _event=None):
        self.note.schedule(self.text)

    def _leave(self, _event=None):
        self.note.hide()


class TableTooltip:
    """Notes for a table's cells: text_for(row id, column id like '#2') -> the note, or "" for none."""

    def __init__(self, tree, text_for):
        self.tree, self.text_for = tree, text_for
        self.note = _Note(tree)
        self.cell = None
        tree.bind("<Motion>", self._move, add="+")
        tree.bind("<Leave>", self._leave, add="+")
        tree.bind("<ButtonPress>", self._leave, add="+")

    def _move(self, event):
        try:
            cell = (self.tree.identify_row(event.y), self.tree.identify_column(event.x))
        except Exception:
            return
        if cell == self.cell:
            return
        self.cell = cell
        self.note.hide()
        if cell[0]:
            self.note.schedule(lambda: self.text_for(*cell), event.x_root, event.y_root)

    def _leave(self, _event=None):
        self.cell = None
        self.note.hide()
