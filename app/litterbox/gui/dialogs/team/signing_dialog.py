"""
signing_dialog.py - switching signed commits on or off for this computer, and showing your public key.
"""

from tkinter import messagebox

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import release_button
from litterbox.team import commit_signing as signing


class SigningDialog(ctk.CTkToplevel):
    """Turn signed commits on or off for this vault and show the public key to give an Admin."""

    def __init__(self, parent, repo):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.repo = repo
        self.title("Signing")
        window_chrome.set_size(self, 560, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.state_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=520)
        self.state_label.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Your public key (give this to an Admin; it is safe to share):", anchor="w",
                     text_color=theme.MUTED).grid(row=1, column=0, sticky="ew", padx=20)
        self.key_box = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, height=110, wrap="word")
        self.key_box.grid(row=2, column=0, sticky="nsew", padx=20, pady=(4, 8))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        for column, (text, command, color, hover) in enumerate((
                ("Turn on signing", self._on, theme.ACCENT, "#18527f"), ("Copy public key", self._copy, theme.GRAY, theme.GRAY_HOVER),
                ("Turn off", self._off, theme.GRAY, theme.GRAY_HOVER), ("Close", self.destroy, theme.GRAY, theme.GRAY_HOVER))):
            release_button.ReleaseButton(buttons, text=text, width=120, fg_color=color, hover_color=hover,
                          command=command).grid(row=0, column=column, padx=(0, 6))
        self._show()
        self.after(100, self.lift)

    def _show(self):
        state = signing.status(self.repo)
        text = "Signing is ON for this vault." if state.enabled else "Signing is off for this vault."
        if state.problems:
            text += "\n" + "\n".join(state.problems)
        self.state_label.configure(text=text)
        self.key_box.configure(state="normal")
        self.key_box.delete("1.0", "end")
        self.key_box.insert("1.0", state.public_key)
        self.key_box.configure(state="disabled")

    def _on(self):
        try:
            signing.enable(self.repo)
        except LitterboxError as e:
            messagebox.showerror("Signing", str(e))
        self._show()

    def _off(self):
        signing.disable(self.repo)
        self._show()

    def _copy(self):
        key = signing.status(self.repo).public_key
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)
