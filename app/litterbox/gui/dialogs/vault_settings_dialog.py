"""
vault_settings_dialog.py - Vault Settings (Admin and Owner): commit style, release rule, signed commits.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class VaultSettingsDialog(modal_dialog.ModalDialog):
    """The vault's shared settings, as one dict: commit_style, release_rule, require_signatures (see config.py).
    show() gives the chosen values (all three) or None."""

    COMMITS = {"One commit per part (default)": "per_part", "One commit for the whole batch (faster)": "per_batch"}
    RULES = {"Warn, and let me go ahead (default)": "warn", "Block the release": "block", "Say nothing": "off"}
    SIGNATURES = {"Not required (default)": False, "Required: refuse unsigned commits": True}

    def __init__(self, parent, current=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        current = current or {}
        self.result = None
        width, height = 560, 520
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title("Vault settings")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Vault settings", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 0))
        ctk.CTkLabel(self, text="These apply to everyone in the vault.", anchor="w", text_color=theme.MUTED).grid(
            row=1, column=0, sticky="ew", padx=20, pady=(0, 6))
        self.vars = {}
        row = 2
        for key, title, choices, note in (
                ("commit_style", "When several parts are checked in or saved at once:", self.COMMITS,
                 "One commit per part keeps each part's history separate. One commit for the batch is faster "
                 "(each commit takes about a second), but every part's history shows the whole batch's commit."),
                ("release_rule", "When a release uses parts that are out of date or not released:", self.RULES,
                 "This is about an assembly's parts, checked when you release it."),
                ("require_signatures", "Signed commits:", self.SIGNATURES,
                 "If required, Litterbox refuses to upload a commit that is not signed by a key on the team "
                 "list. Everyone must have signing set up first (Team > Signing...), or they cannot upload.")):
            names = {value: label for label, value in choices.items()}
            var = tk.StringVar(value=names.get(current.get(key), next(iter(choices))))
            self.vars[key] = (var, choices)
            ctk.CTkLabel(self, text=title, anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(8, 0))
            ctk.CTkOptionMenu(self, variable=var, values=list(choices), width=510, fg_color=theme.GRAY,
                              button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
                row=row + 1, column=0, padx=20, pady=(4, 0), sticky="w")
            ctk.CTkLabel(self, text=note, anchor="w", justify="left", wraplength=510, text_color=theme.MUTED).grid(
                row=row + 2, column=0, sticky="ew", padx=20, pady=(4, 0))
            row += 3
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=row, column=0, sticky="ew", padx=20, pady=(14, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._ok).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(150, self._grab)

    def _ok(self):
        self.result = {key: choices[var.get()] for key, (var, choices) in self.vars.items()}
        self.destroy()
