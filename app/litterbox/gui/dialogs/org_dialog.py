"""
org_dialog.py - Org setup...: an org's code, vault folder, first part number and digits.
"""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from litterbox.core import part_number
from litterbox.core.part_number import PNError, check_org
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import release_button


class OrgDialog(ctk.CTkToplevel):
    """Set up an org: its code, its vault folder, and the first part number it hands out.

        result = OrgDialog(parent, org="HCR", folder=r"C:\\...", start=1, base_digits=5, variant_digits=3).show()
        # None if cancelled, else (org, folder, start, base_digits, variant_digits)
    """

    def __init__(self, parent, org="", folder="", start=1, base_digits=5, variant_digits=3, title="Org setup",
                 save_text="Save"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 520, 420
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        self.org_var = tk.StringVar(value=org)
        self.folder_var = tk.StringVar(value=folder)
        self.start_var = tk.StringVar(value=str(start))
        self.base_digits_var = tk.StringVar(value=str(base_digits))
        self.variant_digits_var = tk.StringVar(value=str(variant_digits))

        ctk.CTkLabel(self, text="Org code (2 to 4 letters, for example HCR)", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        ctk.CTkEntry(self, textvariable=self.org_var, height=34).grid(row=1, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Vault folder", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(12, 2))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=20)
        row.columnconfigure(0, weight=1)
        ctk.CTkEntry(row, textvariable=self.folder_var, height=34).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        release_button.ReleaseButton(row, text="Browse", width=90, height=34, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._browse).grid(row=0, column=1)

        ctk.CTkLabel(self, text="First part number to hand out (for example 10001)", anchor="w").grid(
            row=4, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.start_var, height=34, width=140).grid(
            row=5, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="Digits in the part number and in the variant (for example 6 and 3)", anchor="w").grid(
            row=6, column=0, sticky="ew", padx=20, pady=(12, 2))
        digits = ctk.CTkFrame(self, fg_color="transparent")
        digits.grid(row=7, column=0, sticky="w", padx=20)
        ctk.CTkEntry(digits, textvariable=self.base_digits_var, height=34, width=70).grid(row=0, column=0)
        ctk.CTkLabel(digits, text="-", width=18).grid(row=0, column=1)
        ctk.CTkEntry(digits, textvariable=self.variant_digits_var, height=34, width=70).grid(row=0, column=2)
        ctk.CTkLabel(digits, text="Can't be changed once part numbers exist.", text_color=theme.MUTED).grid(
            row=0, column=3, padx=(14, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=8, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text=save_text, height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _browse(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.folder_var.get() or "C:\\")
        if folder:
            self.folder_var.set(os.path.normpath(folder))

    def _save(self):
        try:
            org = check_org(self.org_var.get().strip()).upper()
        except PNError as e:
            messagebox.showwarning("Org setup", str(e), parent=self)
            return
        folder = self.folder_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("Org setup", "Choose the vault folder for this org.", parent=self)
            return
        text = self.start_var.get().strip()
        if not text.isdigit() or int(text) < 1:
            messagebox.showwarning("Org setup", "The first part number must be a whole number, 1 or higher.",
                                   parent=self)
            return
        try:
            base_digits = number_input.parse_digit_count(self.base_digits_var.get(), "part number digits", *part_number.BASE_DIGITS_RANGE)
            variant_digits = number_input.parse_digit_count(self.variant_digits_var.get(), "variant digits",
                                                     *part_number.VARIANT_DIGITS_RANGE)
        except ValueError as e:
            messagebox.showwarning("Org setup", str(e), parent=self)
            return
        self.result = (org, folder, int(text), base_digits, variant_digits)
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.result
