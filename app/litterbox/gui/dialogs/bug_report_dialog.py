"""
bug_report_dialog.py - Help > Report a problem: what goes in the report, and the comment it needs (what you were
doing when the problem happened). show() gives the comment, or None for Cancel.
"""

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import bug_report_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class BugReportDialog(modal_dialog.ModalDialog):
    FOCUS = "comment"

    def __init__(self, parent, address, problems=0):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 580, 520
        self.title("Report a problem")
        window_chrome.place_over(self, parent, width, height)
        window_chrome.min_size(self, 460, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="Report a problem", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text=bug_report_text.intro(address, problems), anchor="w", justify="left",
                     wraplength=width - 40, text_color=theme.MUTED).grid(row=1, column=0, sticky="ew", padx=20)
        ctk.CTkLabel(self, text=bug_report_text.PROMPT + ":", anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(14, 2))
        self.comment = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, wrap="word", font=ctk.CTkFont(size=13))
        self.comment.grid(row=3, column=0, sticky="nsew", padx=20)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=4, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Make the report", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._confirm).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _confirm(self):
        comment = self.comment.get("1.0", "end").strip()
        if not comment:
            self.problem.configure(text=bug_report_text.NEEDS_COMMENT)
            return
        self.result = comment
        self.destroy()
