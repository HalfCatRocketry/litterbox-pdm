"""
template_choice_dialog.py - New Model... and New Drawing...: which of the vault's templates to make a part's file
from (parts/from_template.py), its default chosen to start with.

    file = TemplateChoiceDialog(parent, "New Drawing", "HCR-00042-001_A.SLDDRW", templates).show()
    # None if cancelled, else the template's file name
"""

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import template_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class TemplateChoiceDialog(modal_dialog.ModalDialog):
    def __init__(self, parent, title, file_name, templates, note=""):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.choices = template_text.choice_map(templates, none=False)
        width, height = 560, 300
        self.title(title)
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"Make {file_name} from", font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 6))
        self.menu = ctk.CTkOptionMenu(self, values=list(self.choices), width=width - 40, height=34,
                                      fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                      button_hover_color=theme.ACCENT, dynamic_resizing=False)
        self.menu.set(next(iter(self.choices)))
        self.menu.grid(row=1, column=0, sticky="w", padx=20)
        ctk.CTkLabel(self, text=note or "Litterbox makes the file in the cad folder, then opens it in SolidWorks. It "
                                        "goes up with your next Check In.", text_color=theme.MUTED, anchor="w",
                     justify="left", wraplength=width - 40).grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=20)
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Make", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._make).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._make())
        self.after(150, self._grab)

    def _make(self):
        self.result = self.choices.get(self.menu.get())
        self.destroy()
