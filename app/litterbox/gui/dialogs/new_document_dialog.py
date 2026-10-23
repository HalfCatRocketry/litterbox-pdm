"""
new_document_dialog.py - New Document: its type (which gives its number's prefix), a title and a description.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class NewDocumentDialog(modal_dialog.ModalDialog):
    """NewDocumentDialog(parent, types).show() -> None if cancelled, else {"type": key, "title": ..., "description":
    ...}. `types` are the DocTypes New Document may use (not hidden)."""
    FOCUS = "title_entry"

    def __init__(self, parent, types):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.types = None, list(types)
        width, height = 500, 330
        self.title("New Document")
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Type", anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        labels = [t.label() for t in self.types]
        self.type_var = tk.StringVar(master=self, value=labels[0] if labels else "")
        ctk.CTkOptionMenu(self, variable=self.type_var, values=labels or [""], width=300, height=34,
                          fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT).grid(
            row=1, column=0, sticky="w", padx=20)
        ctk.CTkLabel(self, text="Title (required)", anchor="w").grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 2))
        self.title_entry = ctk.CTkEntry(self, height=34)
        self.title_entry.grid(row=3, column=0, sticky="ew", padx=20)
        ctk.CTkLabel(self, text="Description (optional)", anchor="w").grid(row=4, column=0, sticky="ew", padx=20,
                                                                            pady=(10, 2))
        self.desc_entry = ctk.CTkEntry(self, height=34)
        self.desc_entry.grid(row=5, column=0, sticky="ew", padx=20)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=7, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                     command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Create", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._create).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._create())
        self.after(150, self._grab)

    def _create(self):
        chosen = next((t for t in self.types if t.label() == self.type_var.get()), None)
        title = " ".join(self.title_entry.get().split())
        if chosen is None:
            self.problem.configure(text="Choose a type.")
            return
        if not title:
            self.problem.configure(text="A title is required.")
            return
        self.result = {"type": chosen.key, "title": title, "description": self.desc_entry.get().strip()}
        self.destroy()
