"""
history_window.py - one part's details in a window of its own (the pop-out of the main window's details pane, to
keep a part in view or compare two side by side), with the same five tabs. The tabs are panes/part_details.py.
"""

import customtkinter as ctk

from litterbox.gui import window_chrome
from litterbox.gui.panes import part_details


class HistoryWindow(ctk.CTkToplevel):
    """A pop-up about one part. `revisions` is {revision: [files]}; `currency` the team's (for costs); the callbacks are PartDetailsView's (on_open,
    on_view_eco, on_tab, on_bom, ...). `loaded` holds what the window has asked to be read ("references", "bom")."""

    def __init__(self, parent, record, revisions=None, currency=None, **callbacks):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.loaded = set()
        self.title(f"{record.pn} - Details")
        window_chrome.set_size(self, 860, 640)
        window_chrome.min_size(self, 580, 440)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"{record.pn}   {record.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        self.view = part_details.PartDetailsView(self, **callbacks)
        self.view.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.view.show(record, revisions, currency)
        self.after(100, self.lift)
