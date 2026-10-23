"""
bom_item_dialog.py - Add item... on the BOM tab: pick a part to list in an assembly's BOM by hand, and how many.
The Documents tab's Add... uses it too, to pick a document to link (no quantity).
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import request_parts
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class BomItemDialog(modal_dialog.ModalDialog):
    """Pick one part from `rows` (PartStatus rows, bom_text.item_choices) and type a quantity.

        BomItemDialog(parent, assembly_pn, rows, note).show()    # None if cancelled, else (PN, quantity text)

    With heading=... and quantity=False it picks a document to link instead: (number, None).
    """
    FOCUS = "entry"

    def __init__(self, parent, assembly_pn, rows, note, heading=None, quantity=True):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.rows, self.by_iid = None, list(rows), {}
        width, height = 640, 560
        self.title("Add to BOM" if quantity else "Link a document")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.minsize(480, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text=heading or f"Add a part to the BOM of {assembly_pn}", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text=note, text_color=theme.MUTED, anchor="w", justify="left", wraplength=590).grid(
            row=1, column=0, sticky="ew", padx=20, pady=(0, 6))
        self.search_var = tk.StringVar()
        self.entry = ctk.CTkEntry(self, textvariable=self.search_var, height=34,
                                  placeholder_text="Search by part number, name or description")
        self.entry.grid(row=2, column=0, sticky="ew", padx=20)
        self.search_var.trace_add("write", lambda *_: self._fill())
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        scale = scaling.scale_of(self)
        self.tree = ttk.Treeview(frame, columns=("pn", "name", "state"), show="headings", selectmode="browse")
        for name, title, size in (("pn", "Part", 150), ("name", "Name", 250), ("state", "State", 140)):
            self.tree.heading(name, text=title, anchor="w")
            self.tree.column(name, width=int(size * scale), anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.quantity = None
        if quantity:
            box = ctk.CTkFrame(self, fg_color="transparent")
            box.grid(row=4, column=0, sticky="w", padx=20, pady=(8, 0))
            ctk.CTkLabel(box, text="Quantity:").grid(row=0, column=0, padx=(0, 8))
            self.quantity = ctk.CTkEntry(box, width=90, height=32)
            self.quantity.grid(row=0, column=1)
            self.quantity.insert(0, "1")
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                     command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Add", height=38, fg_color=theme.GREEN,
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
        for row in request_parts.search(self.rows, self.search_var.get()):
            iid = str(row.pn)
            self.by_iid[iid] = row.pn
            self.tree.insert("", "end", iid=iid, values=(iid, row.name, row.state))
        if not self.rows:
            self.problem.configure(text="There are no parts that can be added here.")

    def _add(self):
        chosen = [self.by_iid[iid] for iid in self.tree.selection() if iid in self.by_iid]
        if not chosen:
            self.problem.configure(text="Pick a part first.")
            return
        self.result = (chosen[0], self.quantity.get() if self.quantity is not None else None)
        self.destroy()
