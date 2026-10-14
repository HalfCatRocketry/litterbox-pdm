"""
revision_picker.py - choosing which revision of a part to open.
"""


import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class RevisionPickerDialog(modal_dialog.ModalDialog):
    """Ask which revision of a part to open. Click a button; the first one is also the Enter key.

        rev = RevisionPickerDialog(parent, pn, [("Rev B (working)", "B"), ("Rev A (released)", "A")]).show()
        # None if cancelled
    """

    def __init__(self, parent, pn, choices, title="Open"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width = 380
        height = 100 + 46 * len(choices)
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(f"{title} {pn.short}")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"Which revision of {pn.short}?", font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        for number, (label, rev) in enumerate(choices):
            release_button.ReleaseButton(self, text=label, height=38, fg_color=theme.ACCENT if number == 0 else theme.GRAY,
                          hover_color="#18527f" if number == 0 else theme.GRAY_HOVER,
                          command=lambda rev=rev: self._choose(rev)).grid(
                row=number + 1, column=0, sticky="ew", padx=20, pady=3)
        self.first = choices[0][1]
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._choose(self.first))
        self.after(150, self._grab)

    def _choose(self, rev):
        self.result = rev
        self.destroy()
