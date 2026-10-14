"""
filename_dialog.py - shows the file name a part's CAD file must have (to copy into Save As).
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.core import filenames
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import release_button


class FilenameDialog(ctk.CTkToplevel):
    """Shown after New Part: the exact file name to save the CAD file as, with a Copy button."""

    def __init__(self, parent, pn, revision="A"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.stem = filenames.file_stem(pn, revision)
        width, height = 520, 230
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Part created")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=f"Created {pn}", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text="Save your SolidWorks file in the cad folder with this name "
                                "(SolidWorks adds the extension):", anchor="w", justify="left",
                     wraplength=width - 40, text_color=theme.MUTED).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=20)
        self.entry = ctk.CTkEntry(self, height=36, font=ctk.CTkFont(family="Consolas", size=14))
        self.entry.grid(row=2, column=0, sticky="ew", padx=(20, 6), pady=10)
        self.entry.insert(0, self.stem)
        self.entry.configure(state="readonly")
        self.copy_button = release_button.ReleaseButton(self, text="Copy filename", height=36, width=130,
                                         fg_color=theme.ACCENT, hover_color="#18527f", command=self._copy)
        self.copy_button.grid(row=2, column=1, padx=(0, 20), pady=10)
        release_button.ReleaseButton(self, text="Close", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(6, 18))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._copy())
        self.after(150, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def _copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.stem)
        self.copy_button.configure(text="Copied")
