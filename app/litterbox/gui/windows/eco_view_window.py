"""
eco_view_window.py - one engineering change order: its title, description, parts (with what changed and the Dispo),
sign-offs and history. Read-only.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import eco_text


class EcoViewWindow(ctk.CTkToplevel):
    """A pop-up showing one ECO (change_orders/eco_model.Eco)."""

    def __init__(self, parent, eco):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title(f"{eco.number} - {eco.name}")
        window_chrome.set_size(self, 720, 640)
        window_chrome.min_size(self, 520, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        header.columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text=f"{eco.number}   {eco.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, columnspan=2, sticky="w")
        for number, (label, text) in enumerate(eco_text.eco_fields(eco), 1):
            ctk.CTkLabel(header, text=label + ":", text_color=theme.MUTED, anchor="nw").grid(
                row=number, column=0, sticky="nw", padx=(0, 10))
            ctk.CTkLabel(header, text=text, anchor="nw", justify="left", wraplength=560).grid(
                row=number, column=1, sticky="nw")      # top-aligned with its label, even wrapped

        description = ctk.CTkTextbox(self, height=90, fg_color=theme.BG_PANEL, wrap="word")
        description.grid(row=1, column=0, sticky="ew", padx=20, pady=(4, 8))
        description.insert("1.0", eco.description or "(no description)")
        description.configure(state="disabled")

        self.parts = self._table(2, eco_text.PART_COLUMNS, eco_text.part_rows(eco), 4)
        tabs = ctk.CTkTabview(self, fg_color=theme.BG_PANEL, height=200)
        tabs.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 20))
        for name in ("Sign-offs", "History"):
            tabs.add(name)
            tabs.tab(name).columnconfigure(0, weight=1)
            tabs.tab(name).rowconfigure(0, weight=1)
        signoffs = eco_text.signoff_rows(eco)
        self.signoffs = self._tree(tabs.tab("Sign-offs"), (("who", "Who", 160), ("when", "When", 130),
                                                          ("comment", "Comment", 320)),
                                   signoffs or [("(none yet)", "", "")])
        self.history = self._tree(tabs.tab("History"), (("when", "When", 130), ("who", "Who", 160),
                                                       ("what", "What", 320)), eco_text.history_rows(eco))
        self.after(100, self.lift)

    def _table(self, row, columns, values, height):
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = self._tree(frame, columns, values)
        tree.configure(height=min(max(len(values), 1), height))
        return tree

    def _tree(self, parent, columns, values):
        tree = ttk.Treeview(parent, columns=[name for name, _title, _w in columns], show="headings",
                            selectmode="browse")
        for name, title, width in columns:
            tree.heading(name, text=title, anchor="w")
            tree.column(name, width=width, anchor="w")
        for value in values:
            tree.insert("", "end", values=value)
        tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        return tree
