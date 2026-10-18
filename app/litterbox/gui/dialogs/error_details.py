"""
error_details.py - the Details... window behind the red status bar: what went wrong and what to do.
"""

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import release_button


class ErrorDetailsWindow(ctk.CTkToplevel):
    """The problems behind the red status bar: what Litterbox was doing, what went wrong, and what to do about it."""

    def __init__(self, parent, text, on_dismiss):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title("What went wrong")
        self.geometry("720x480")
        self.minsize(520, 320)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.box = ctk.CTkTextbox(self, wrap="word")
        self.box.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=1, column=0, sticky="e", padx=16, pady=(0, 14))
        release_button.ReleaseButton(buttons, text="Copy", width=90, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=lambda: self._copy(text)).grid(row=0, column=0, padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Dismiss all", width=110, fg_color=theme.RED, hover_color=theme.RED_HOVER,
                      command=lambda: (on_dismiss(), self.destroy())).grid(row=0, column=1, padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Close", width=90, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=2)
        self.after(100, self.lift)

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
