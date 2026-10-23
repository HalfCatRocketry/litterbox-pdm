"""
edit_details_dialog.py - Edit Details: a part's name and description, and its kind (CAD or non-CAD) while it may
still change.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import confirmations
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.records import record_model


class EditDetailsDialog(modal_dialog.ModalDialog):
    """Change a part's name and description, and its kind.

        EditDetailsDialog(parent, pn, name, description, kind, kind_note).show()
        # None if cancelled or nothing changed, else (name, description, kind)

    `kind` is the part's kind (record_model.KIND_CAD or KIND_NONCAD). `kind_note` is why it can't change ("" if it
    can): then the choice is greyed out.
    """
    FOCUS = "name_entry"

    def __init__(self, parent, pn, name, description, kind=record_model.KIND_CAD, kind_note=""):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.old = (name, description)
        self.old_kind = kind
        width, height = 500, 390
        self.title("Edit Details")
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text=str(pn), font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Name (required)", anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        self.name_entry = ctk.CTkEntry(self, height=34)
        self.name_entry.grid(row=2, column=0, sticky="ew", padx=20)
        self.name_entry.insert(0, name)
        ctk.CTkLabel(self, text="Description (optional)", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.desc_entry = ctk.CTkEntry(self, height=34)
        self.desc_entry.grid(row=4, column=0, sticky="ew", padx=20)
        self.desc_entry.insert(0, description)
        ctk.CTkLabel(self, text="Kind", anchor="w").grid(row=5, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.kind_var = tk.StringVar(master=self, value=record_model.KIND_LABEL[kind])
        ctk.CTkOptionMenu(self, variable=self.kind_var, values=[record_model.KIND_LABEL[k] for k in record_model.ALL_KINDS],
                          width=160, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          state="disabled" if kind_note else "normal").grid(row=6, column=0, sticky="w", padx=20)
        ctk.CTkLabel(self, text=kind_note, text_color=theme.MUTED, anchor="w", justify="left", wraplength=450).grid(
            row=7, column=0, sticky="ew", padx=20)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=8, column=0, sticky="ew", padx=20, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=9, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._save())
        self.after(150, self._grab)

    def _save(self):
        name, description = self.name_entry.get(), self.desc_entry.get()
        problem, changed = confirmations.edit_details_result(*self.old, name, description)
        self.problem.configure(text=problem)
        if problem:
            return
        kind = {label: key for key, label in record_model.KIND_LABEL.items()}.get(self.kind_var.get(), self.old_kind)
        if changed or kind != self.old_kind:
            self.result = (name, description, kind)
        self.destroy()
