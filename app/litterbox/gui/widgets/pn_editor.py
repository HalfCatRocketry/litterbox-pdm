"""
pn_editor.py - PnEditor: the little base / variant editor placed over a cell of the Import table.
"""

import tkinter as tk

from litterbox.core import part_number
from litterbox.gui import theme


class PnEditor:
    """The part number editor placed over a table cell: ORG-[base box]-[variant box], like New Part.

    get() returns (base text, variant text). Enter in the first box moves to the second; Enter in the
    second box, or leaving both boxes, calls on_commit; Escape calls on_cancel.
    """

    def __init__(self, parent, org, base, variant, on_commit, on_cancel):
        self.on_commit = on_commit
        self.frame = tk.Frame(parent, bg="#1f1f1f", highlightthickness=1, highlightbackground=theme.ACCENT)
        label = dict(bg="#1f1f1f", fg="#e6e6e6", font=("Segoe UI", 10))
        tk.Label(self.frame, text=f"{org}-", **label).pack(side="left", padx=(6, 0))
        options = dict(font=("Segoe UI", 10), bg="#2b2b2b", fg="#ffffff", insertbackground="#ffffff",
                       relief="flat", justify="center")
        self.base_box = tk.Entry(self.frame, width=part_number.BASE_DIGITS + 1, **options)
        self.base_box.pack(side="left")
        tk.Label(self.frame, text="-", **label).pack(side="left")
        self.variant_box = tk.Entry(self.frame, width=part_number.VARIANT_DIGITS + 1, **options)
        self.variant_box.pack(side="left", padx=(0, 6))
        self.base_box.insert(0, base)
        self.variant_box.insert(0, variant)
        for box in (self.base_box, self.variant_box):
            box.bind("<Escape>", lambda e: on_cancel())
            box.bind("<FocusOut>", lambda e: self.frame.after(60, self._left))
        self.base_box.bind("<Return>", lambda e: self.variant_box.focus_set())
        self.base_box.bind("-", lambda e: (self.variant_box.focus_set(), "break")[1])
        self.variant_box.bind("<Return>", lambda e: on_commit())

    def place(self, x, y, width, height):
        self.frame.place(x=x, y=y, width=width, height=height)
        self.base_box.focus_set()
        self.base_box.select_range(0, "end")

    def _left(self):
        """Commit once focus has left both boxes (moving from one box to the other does not count)."""
        try:
            if self.frame.focus_get() in (self.base_box, self.variant_box):
                return
        except (tk.TclError, KeyError):
            pass
        self.on_commit()

    def get(self):
        return self.base_box.get(), self.variant_box.get()

    def destroy(self):
        self.frame.destroy()
