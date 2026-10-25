"""
git_identity_dialog.py - asking for the name and email address git puts on your commits in this vault
(git/git_identity.py): when git doesn't know them, or offering the team list's name when git has another.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.errors import LitterboxError
from litterbox.git import git_identity
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import git_identity_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class GitIdentityDialog(modal_dialog.ModalDialog):
    """    result = GitIdentityDialog(parent, wanted, vault_name).show()     # None (left as it is) or (name, email)
    `wanted` is git_identity.Wanted. The answer is checked (git_identity.check) before it returns."""
    FOCUS = "entry"

    def __init__(self, parent, wanted, vault_name=""):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 520, 340
        self.title(git_identity_text.TITLE)
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(1, weight=1)
        ctk.CTkLabel(self, text=git_identity_text.intro(wanted, vault_name), anchor="w", justify="left",
                     wraplength=width - 40).grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 10))
        self.name_var, self.email_var = tk.StringVar(value=wanted.name), tk.StringVar(value=wanted.email)
        ctk.CTkLabel(self, text="Name:").grid(row=1, column=0, sticky="w", padx=(20, 8), pady=4)
        self.entry = ctk.CTkEntry(self, textvariable=self.name_var, height=32)
        self.entry.grid(row=1, column=1, sticky="ew", padx=(0, 20), pady=4)
        ctk.CTkLabel(self, text="Email:").grid(row=2, column=0, sticky="w", padx=(20, 8), pady=4)
        ctk.CTkEntry(self, textvariable=self.email_var, height=32).grid(row=2, column=1, sticky="ew", padx=(0, 20),
                                                                         pady=4)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text=git_identity_text.cancel_text(wanted), height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._confirm).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._confirm())
        self.after(150, self._grab)

    def _confirm(self):
        try:
            self.result = git_identity.check(self.name_var.get(), self.email_var.get())
        except LitterboxError as e:
            self.problem.configure(text=str(e))
            return
        self.destroy()
