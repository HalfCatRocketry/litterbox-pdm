"""
clone_dialog.py - Add org...: paste the vault's repository URL.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import release_button
from litterbox.vault import clone as vault_clone


class CloneDialog(ctk.CTkToplevel):
    """Add org...: the URL of a vault on the Git host. show() gives the URL typed, or None."""

    def __init__(self, parent, root):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.root = None, root
        width, height = 560, 250
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Add org")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Repository URL", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text="On your Git host, press Clone and copy the https address.", text_color=theme.MUTED,
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        self.url_var = tk.StringVar()
        self.entry = ctk.CTkEntry(self, textvariable=self.url_var, height=34,
                                  placeholder_text="https://dev.azure.com/team/project/_git/hcr-litterbox")
        self.entry.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.where = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=520)
        self.where.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.url_var.trace_add("write", lambda *_: self._preview())
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(14, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Add", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._ok).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Return>", lambda event: self._ok())
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _preview(self):
        name, problem = vault_clone.parse_url(self.url_var.get())
        if self.url_var.get().strip() and not problem:
            self.where.configure(text=f"It will be copied to {vault_clone.target_folder(self.root, name)}",
                                 text_color=theme.MUTED)
        else:
            self.where.configure(text="")

    def _ok(self):
        name, problem = vault_clone.parse_url(self.url_var.get())
        if problem:
            self.where.configure(text=problem, text_color=theme.ERROR)
            return
        self.result = self.url_var.get().strip()
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result
