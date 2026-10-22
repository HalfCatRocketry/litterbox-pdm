"""
purchasing_dialog.py - Purchasing Info: a part's supplier, supplier part number, unit cost and lead time.
"""

import customtkinter as ctk

from litterbox.core import currency as currencies
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import purchasing_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.records import purchasing_info

HINTS = {purchasing_info.UNIT_COST: "a number, like 12.50", purchasing_info.LEAD_TIME_DAYS: "whole days"}


class PurchasingDialog(modal_dialog.ModalDialog):
    """Change a part's purchasing fields.

        PurchasingDialog(parent, pn, section, note, currency="USD").show()
        # None if cancelled or nothing changed, else {field: text}

    The unit cost box has the team's currency symbol beside it ($ before it, kr after it); without a currency it
    says the cost is in the team's own currency.
    """
    FOCUS = "first_entry"

    def __init__(self, parent, pn, section, note="", currency=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.old = None, dict(section or {})
        width, height = 500, 430 + (30 if note else 0)
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Purchasing Info")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=str(pn), font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        row = 1
        if note:
            ctk.CTkLabel(self, text=note, text_color=theme.MUTED, anchor="w", justify="left", wraplength=450).grid(
                row=row, column=0, sticky="ew", padx=20, pady=(0, 4))
            row += 1
        self.entries = {}
        for key in purchasing_info.FIELDS:
            label = purchasing_info.LABELS[key] + (f" ({HINTS[key]})" if key in HINTS else "")
            if key == purchasing_info.UNIT_COST and not currencies.symbol(currency):
                label = purchasing_info.LABELS[key] + " (a number in your team's currency, like 12.50)"
            ctk.CTkLabel(self, text=label, anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(8, 0))
            holder = ctk.CTkFrame(self, fg_color="transparent")
            holder.grid(row=row + 1, column=0, sticky="ew", padx=20)
            holder.columnconfigure(1, weight=1)
            entry = ctk.CTkEntry(holder, height=32)
            entry.grid(row=0, column=1, sticky="ew")
            if key == purchasing_info.UNIT_COST and currencies.symbol(currency):
                after = currencies.symbol_after(currency)
                ctk.CTkLabel(holder, text=currencies.symbol(currency), font=ctk.CTkFont(size=15)).grid(
                    row=0, column=2 if after else 0, padx=(6, 0) if after else (0, 6))
            entry.insert(0, purchasing_info.shown(self.old, key))
            self.entries[key] = entry
            row += 2
        self.first_entry = self.entries[purchasing_info.FIELDS[0]]
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=row, column=0, sticky="ew", padx=20, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=row + 1, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._save).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._save())
        self.after(150, self._grab)

    def _save(self):
        typed = {key: entry.get() for key, entry in self.entries.items()}
        problem, fields = purchasing_text.dialog_result(self.old, typed)
        self.problem.configure(text=problem)
        if problem:
            return
        self.result = fields
        self.destroy()
