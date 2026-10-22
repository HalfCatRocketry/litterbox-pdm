"""
vault_settings_dialog.py - Vault Settings (Admin and Owner): the org name (Owner only), commit style, release rule,
signed commits, the variant assemblies start at, the SolidWorks version everyone works in, and the team's currency.
"""

import datetime
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import release_button
from litterbox.cad import solidworks_versions
from litterbox.core import currency
from litterbox.vault import config

ANY_VERSION = "Any version (no check)"
NO_CURRENCY = "None (numbers only)"


class VaultSettingsDialog(modal_dialog.ModalDialog):
    """The vault's shared settings, as one dict: org_name, commit_style, release_rule, require_signatures,
    assembly_variant_start, solidworks_version and currency (see config.py). show() gives the chosen values or None; org_name is
    only among them when may_rename (the Owner), otherwise it is shown but can't be edited. `installed` is the year
    of this computer's SolidWorks (None without one), shown under the SolidWorks choice."""

    COMMITS = {"One commit per part (default)": "per_part", "One commit for the whole batch (faster)": "per_batch"}
    RULES = {"Warn, and let me go ahead (default)": "warn", "Block the release": "block", "Say nothing": "off"}
    SIGNATURES = {"Not required (default)": False, "Required: refuse unsigned commits": True}

    def __init__(self, parent, current=None, may_rename=False, installed=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        current = current or {}
        self.result, self.may_rename = None, may_rename
        width, height = 560, 820
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
        ctk.CTkLabel(self, text="Organization name", anchor="w").grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.name_var = tk.StringVar(value=current.get("org_name") or "")
        ctk.CTkEntry(self, textvariable=self.name_var, width=510, height=32,
                     state="normal" if may_rename else "disabled").grid(row=3, column=0, padx=20, pady=(4, 0), sticky="w")
        ctk.CTkLabel(self, text="Shown beside the org code. " + ("" if may_rename else "Only the Owner can change it."),
                     anchor="w", justify="left", wraplength=510, text_color=theme.MUTED).grid(
            row=4, column=0, sticky="ew", padx=20, pady=(4, 0))
        self.vars = {}
        row = 5
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
        pair = ctk.CTkFrame(self, fg_color="transparent")          # two settings side by side, to keep it short
        pair.grid(row=row, column=0, sticky="ew", padx=20, pady=(8, 0))
        pair.columnconfigure((0, 1), weight=1, uniform="p")
        ctk.CTkLabel(pair, text="New Assembly starts at variant:", anchor="w").grid(row=0, column=0, sticky="ew")
        self.assembly_var = tk.StringVar(value=str(current.get("assembly_variant_start", "")))
        ctk.CTkEntry(pair, textvariable=self.assembly_var, width=90, height=32).grid(
            row=1, column=0, pady=(4, 0), sticky="w")
        ctk.CTkLabel(pair, text="New Part uses the variants below it. Parts already made keep their numbers.",
                     anchor="w", justify="left", wraplength=240, text_color=theme.MUTED).grid(
            row=2, column=0, sticky="new", pady=(4, 0), padx=(0, 10))
        chosen = current.get("solidworks_version")
        self.versions = {ANY_VERSION: None}
        self.versions.update({f"SolidWorks {year}": year for year in solidworks_versions.year_choices(
            datetime.date.today().year, chosen)})
        self.version_var = tk.StringVar(value=f"SolidWorks {chosen}" if chosen else ANY_VERSION)
        ctk.CTkLabel(pair, text="Everyone works in:", anchor="w").grid(row=0, column=1, sticky="ew")
        ctk.CTkOptionMenu(pair, variable=self.version_var, values=list(self.versions), width=240,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
            row=1, column=1, pady=(4, 0), sticky="w")
        ctk.CTkLabel(pair, text="People with a newer SolidWorks can't check out, so nobody saves files others can't "
                                "open. " + (f"This computer has SolidWorks {installed}." if installed
                                            else "This computer has no SolidWorks."),
                     anchor="w", justify="left", wraplength=240, text_color=theme.MUTED).grid(
            row=2, column=1, sticky="new", pady=(4, 0))
        row += 1
        self.currencies = {NO_CURRENCY: None}
        self.currencies.update({currency.label(c.code): c.code for c in currency.CURRENCIES})
        chosen_currency = current.get("currency")
        self.currency_var = tk.StringVar(value=currency.label(chosen_currency) if chosen_currency in currency.BY_CODE
                                         else NO_CURRENCY)
        ctk.CTkLabel(self, text="The team's currency:", anchor="w").grid(row=row, column=0, sticky="ew", padx=20,
                                                                       pady=(10, 0))
        ctk.CTkOptionMenu(self, variable=self.currency_var, values=list(self.currencies), width=510,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
            row=row + 1, column=0, padx=20, pady=(4, 0), sticky="w")
        ctk.CTkLabel(self, text="Costs show its symbol ($12.50). Changing it doesn't convert unit costs.",
                     anchor="w", justify="left", wraplength=510,
                     text_color=theme.MUTED).grid(row=row + 2, column=0, sticky="ew", padx=20, pady=(4, 0))
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
        result = {key: choices[var.get()] for key, (var, choices) in self.vars.items()}
        result["solidworks_version"] = self.versions.get(self.version_var.get())
        result["currency"] = self.currencies.get(self.currency_var.get())
        if self.may_rename:
            try:
                result["org_name"] = config.check_org_name(self.name_var.get())
            except config.ConfigError as e:
                messagebox.showwarning("Vault settings", str(e), parent=self)
                return
        try:
            start = number_input.parse_number(self.assembly_var.get(), "assembly variant")
            result["assembly_variant_start"] = config.check_assembly_variant(start)
        except (ValueError, config.ConfigError) as e:
            messagebox.showwarning("Vault settings", str(e), parent=self)
            return
        self.result = result
        self.destroy()
