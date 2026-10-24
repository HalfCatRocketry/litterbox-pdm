"""
create_variant_dialog.py - Create Variant (Create menu): the new part's name and description (the original's to
start with) and its variant number (the next free one if left empty). The copying is parts/create_variant.py.
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import number_input
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class CreateVariantDialog(modal_dialog.ModalDialog):
    """CreateVariantDialog(parent, pn, name, description, next_free).show() gives {"name", "description",
    "variant" (int or None for the next free one)}, or None for Cancel. `next_free` is the variant suggested."""
    FOCUS = "name_entry"

    def __init__(self, parent, pn, name, description, next_free=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 500, 470
        self.title("Create Variant")
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"A copy of {pn} as a part of its own", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="The new part gets a variant of the same part number, starts at Rev A, and is "
                                "checked out to you, with copies of the latest revision's SolidWorks files.",
                     anchor="w", justify="left", wraplength=width - 40,
                     text_color=theme.MUTED).grid(row=1, column=0, sticky="ew", padx=20)
        self.name_var = tk.StringVar(value=name or "")
        self.desc_var = tk.StringVar(value=description or "")
        self.variant_var = tk.StringVar()
        row = 2
        for label, var, attribute in (("Name (required)", self.name_var, "name_entry"),
                                      ("Description", self.desc_var, "desc_entry")):
            ctk.CTkLabel(self, text=label, anchor="w").grid(row=row, column=0, sticky="ew", padx=20, pady=(12, 2))
            entry = ctk.CTkEntry(self, textvariable=var, height=34)
            entry.grid(row=row + 1, column=0, sticky="ew", padx=20)
            setattr(self, attribute, entry)
            row += 2
        ctk.CTkLabel(self, text="Variant (leave empty for the next free one)", anchor="w").grid(
            row=row, column=0, sticky="ew", padx=20, pady=(12, 2))
        ctk.CTkEntry(self, textvariable=self.variant_var, height=34, width=120,
                     placeholder_text=f"{next_free:03d}" if isinstance(next_free, int) else "next free").grid(
            row=row + 1, column=0, sticky="w", padx=20)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=row + 2, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=row + 3, column=0, sticky="ew", padx=20, pady=(10, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Create", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._ok).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._ok())
        self.after(150, self._grab)

    def _ok(self):
        name = " ".join(self.name_var.get().split())
        if not name:
            self.problem.configure(text="A name is required.")
            return
        variant = None
        if self.variant_var.get().strip():
            try:
                variant = number_input.parse_number(self.variant_var.get(), "variant")
            except ValueError as e:
                messagebox.showwarning("Create Variant", str(e), parent=self)
                return
        self.result = {"name": name, "description": " ".join(self.desc_var.get().split()), "variant": variant}
        self.destroy()
