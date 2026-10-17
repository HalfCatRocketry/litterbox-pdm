"""
history_window.py - one part's Details and History in a window of its own (the pop-out of the main window's
details pane, to keep a part in view or compare two side by side). The tabs are panes/part_details.py.
"""

import customtkinter as ctk

from litterbox.gui import window_chrome
from litterbox.gui.panes import part_details


class HistoryWindow(ctk.CTkToplevel):
    """A pop-up about one part. `revisions` is {revision: [files]}; on_open(rev, drawing) opens a revision's file;
    on_view_eco(number) shows an ECO."""

    def __init__(self, parent, record, revisions=None, on_open=None, on_view_eco=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title(f"{record.pn} - Details and History")
        self.geometry("860x640")
        self.minsize(580, 440)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"{record.pn}   {record.name}", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        self.view = part_details.PartDetailsView(self, on_open=on_open, on_view_eco=on_view_eco)
        self.view.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.view.show(record, revisions)
        self.after(100, self.lift)
