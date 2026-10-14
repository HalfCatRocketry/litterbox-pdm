"""
edit_details_dialog.py - Edit Details: a part's name and description.
"""


import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import confirmations
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class EditDetailsDialog(modal_dialog.ModalDialog):
    """Change a part's name and description.

        EditDetailsDialog(parent, pn, name, description).show()
        # None if cancelled or nothing changed, else (name, description)
    """
    FOCUS = "name_entry"

    def __init__(self, parent, pn, name, description):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.old = (name, description)
        width, height = 500, 300
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Edit Details")
        self.geometry(f"{width}x{height}+{x}+{y}")
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
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 18))
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
        if changed:
            self.result = (name, description)
        self.destroy()
