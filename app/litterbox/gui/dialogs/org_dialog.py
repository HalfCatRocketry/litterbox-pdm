"""
org_dialog.py - Create new vault...: the empty repository's URL, and the new org's code, full name, first part number
and digits (none of which can be changed once the vault exists), and the variant assemblies start at (which an Admin
can change later).
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.core import part_number
from litterbox.core.part_number import PNError, check_org
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.vault import clone as vault_clone
from litterbox.vault import config

TITLE = "Create new vault"


class OrgDialog(modal_dialog.ModalDialog):
    """Create new vault...: where the empty repository is, and the new org's settings.

        result = OrgDialog(parent, root=r"C:\\Litterbox", start=1, base_digits=6, variant_digits=3).show()
        # None if cancelled, else (url, org, start, base_digits, variant_digits, org_name, assembly_variant_start)
    """

    def __init__(self, parent, root, start=1, base_digits=6, variant_digits=3):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.root = None, root
        width, height = 560, 660
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(TITLE)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        self.url_var = tk.StringVar()
        self.org_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.start_var = tk.StringVar(value=str(start))
        self.base_digits_var = tk.StringVar(value=str(base_digits))
        self.variant_digits_var = tk.StringVar(value=str(variant_digits))
        self.assembly_var = tk.StringVar(value=str(config.default_assembly_variant(variant_digits)))
        self.variant_digits_var.trace_add("write", lambda *_: self._follow_variant_digits())

        ctk.CTkLabel(self, text="Empty repository URL (press Clone on your Git host and copy the https address)",
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 2))
        ctk.CTkEntry(self, textvariable=self.url_var, height=34,
                     placeholder_text="https://dev.azure.com/team/project/_git/hcr-litterbox").grid(
            row=1, column=0, sticky="ew", padx=20)
        self.where = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left", wraplength=520)
        self.where.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 0))
        self.url_var.trace_add("write", lambda *_: self._preview())

        ctk.CTkLabel(self, text="Org code (2 to 4 letters, for example HCR)", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.org_var, height=34).grid(row=4, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="Org name (optional, for example Hidden Creek Robotics)", anchor="w").grid(
            row=5, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.name_var, height=34).grid(row=6, column=0, sticky="ew", padx=20)

        ctk.CTkLabel(self, text="First part number to hand out (for example 10001)", anchor="w").grid(
            row=7, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.start_var, height=34, width=140).grid(
            row=8, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="Digits in the part number and in the variant (for example 6 and 3)", anchor="w").grid(
            row=9, column=0, sticky="ew", padx=20, pady=(12, 2))
        digits = ctk.CTkFrame(self, fg_color="transparent")
        digits.grid(row=10, column=0, sticky="w", padx=20)
        ctk.CTkEntry(digits, textvariable=self.base_digits_var, height=34, width=70).grid(row=0, column=0)
        ctk.CTkLabel(digits, text="-", width=18).grid(row=0, column=1)
        ctk.CTkEntry(digits, textvariable=self.variant_digits_var, height=34, width=70).grid(row=0, column=2)

        ctk.CTkLabel(self, text="New Assembly starts at variant (New Part uses the ones below; an Admin can change "
                                "this later)", anchor="w", justify="left", wraplength=520).grid(
            row=11, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.assembly_var, height=34, width=90).grid(row=12, column=0, sticky="w", padx=20)

        ctk.CTkLabel(self, text="The org code, org name and part numbers can't be changed once the vault is created.",
                     text_color=theme.WARN, anchor="w", justify="left", wraplength=520).grid(
            row=13, column=0, sticky="ew", padx=20, pady=(16, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=14, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Create", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _follow_variant_digits(self):
        """Keep the assembly variant at the default for the digits typed (500 for 3), unless it was changed by hand."""
        low, high = part_number.VARIANT_DIGITS_RANGE
        try:
            digits = int(self.variant_digits_var.get())
        except ValueError:
            return
        defaults = {str(config.default_assembly_variant(n)) for n in range(low, high + 1)}
        if low <= digits <= high and self.assembly_var.get().strip() in defaults:
            self.assembly_var.set(str(config.default_assembly_variant(digits)))

    def _preview(self):
        name, problem = vault_clone.parse_url(self.url_var.get())
        if self.url_var.get().strip() and not problem:
            self.where.configure(text=f"It will be copied to {vault_clone.target_folder(self.root, name)}")
        else:
            self.where.configure(text="")

    def _save(self):
        _name, problem = vault_clone.parse_url(self.url_var.get())
        if problem:
            messagebox.showwarning(TITLE, problem, parent=self)
            return
        try:
            org = check_org(self.org_var.get().strip()).upper()
        except PNError as e:
            messagebox.showwarning(TITLE, str(e), parent=self)
            return
        try:
            org_name = config.check_org_name(self.name_var.get())
        except config.ConfigError as e:
            messagebox.showwarning(TITLE, str(e), parent=self)
            return
        text = self.start_var.get().strip()
        if not text.isdigit() or int(text) < 1:
            messagebox.showwarning(TITLE, "The first part number must be a whole number, 1 or higher.", parent=self)
            return
        try:
            base_digits = number_input.parse_digit_count(self.base_digits_var.get(), "part number digits", *part_number.BASE_DIGITS_RANGE)
            variant_digits = number_input.parse_digit_count(self.variant_digits_var.get(), "variant digits",
                                                     *part_number.VARIANT_DIGITS_RANGE)
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e), parent=self)
            return
        try:
            assembly = config.check_assembly_variant(
                number_input.parse_number(self.assembly_var.get(), "assembly variant"), variant_digits)
        except (ValueError, config.ConfigError) as e:
            messagebox.showwarning(TITLE, str(e), parent=self)
            return
        self.result = (self.url_var.get().strip(), org, int(text), base_digits, variant_digits, org_name, assembly)
        self.destroy()
