"""
change_info_dialog.py - asked before a Release or Void that has no workflow: for each part released at Rev B or
later, what changed (form, fit, function) and the Dispo of the earlier revision's parts; for each part voided, the
Dispo of its parts. Every Dispo is required. (A workflow asks the same in its own window, request_dialog.py.)
"""

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import change_text
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import change_table
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button
from litterbox.workflows import workflow_templates


class ChangeInfoDialog(modal_dialog.ModalDialog):
    """show() gives {part number text: {"changed", "disposition"}}, or None if cancelled. `parts` is [(PN, name,
    revision, released revision)]."""

    def __init__(self, parent, action, parts):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        label = workflow_templates.label_of(action)
        width, height = 900, 420
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(label)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(700, 320)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        voiding = workflow_templates.base_action(action) == workflow_templates.VOID
        heading = f"{label}: the parts already made" if voiding else f"{label}: what changed"
        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text=task_text.VOID_HINT if voiding else task_text.CHANGE_HINT, text_color=theme.MUTED,
                     anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.table = change_table.ChangeTable(frame, action, parts, height=min(max(len(parts), 3), 10),
                                              on_change=lambda: self.problem.configure(text=""))
        self.table.tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left",
                                    wraplength=width - 40)
        self.problem.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Continue", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._ok).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _ok(self):
        missing = self.table.missing()
        if missing:
            self.problem.configure(text=change_text.missing_text(missing))
            return
        self.result = self.table.result()
        self.destroy()
