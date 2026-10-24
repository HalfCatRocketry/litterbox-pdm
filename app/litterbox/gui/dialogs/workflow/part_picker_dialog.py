"""
part_picker_dialog.py - Add Parts: search the parts that could be added and pick some. In the Workflow window
(those that could join the request) and on a folder in Home (any part or document not in it yet).
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import request_parts
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class PartPickerDialog(modal_dialog.ModalDialog):
    """Pick parts from `rows` (PartStatus rows that may join the request). Type to search; select one or more
    (Ctrl or Shift for several) and press Add.

        PartPickerDialog(parent, rows, label).show()    # None if cancelled, else [PN] in list order
        PartPickerDialog(parent, rows, heading="Add parts to Brackets", empty="...").show()
    """
    FOCUS = "entry"

    def __init__(self, parent, rows, label="", heading="", empty="No other parts can join this workflow right now."):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.rows = list(rows)
        self.by_iid = {}
        width, height = 640, 520
        self.title("Add Parts")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.minsize(480, 380)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.empty = empty
        ctk.CTkLabel(self, text=heading or f"Add parts to the {label} workflow", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        self.search_var = tk.StringVar()
        self.entry = ctk.CTkEntry(self, textvariable=self.search_var, height=34,
                                  placeholder_text="Search by part number, name or description")
        self.entry.grid(row=1, column=0, sticky="ew", padx=20)
        self.search_var.trace_add("write", lambda *_: self._fill())
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("pn", "name", "state"), show="headings", selectmode="extended")
        for name, title, size in (("pn", "Part", 150), ("name", "Name", 250), ("state", "State", 120)):
            self.tree.heading(name, text=title, anchor="w")
            self.tree.column(name, width=size, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", lambda event: self._add())
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w")
        self.note.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                     command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Add selected", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._add).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._add())
        self.after(150, self._grab)

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        self.by_iid = {}
        shown = request_parts.search(self.rows, self.search_var.get())
        for row in shown:
            iid = str(row.pn)
            self.by_iid[iid] = row.pn
            self.tree.insert("", "end", iid=iid, values=(iid, row.name, row.state))
        if not self.rows:
            self.note.configure(text=self.empty)
        else:
            self.note.configure(text=f"{len(shown)} of {len(self.rows)} parts shown. Ctrl or Shift selects several.")

    def _add(self):
        chosen = [self.by_iid[iid] for iid in self.tree.selection() if iid in self.by_iid]
        if not chosen:
            self.note.configure(text="Select one or more parts first.")
            return
        self.result = chosen
        self.destroy()
