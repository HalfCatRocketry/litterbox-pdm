"""
bug_report_dialog.py - Help > Report a problem: exactly what goes in the report (each file, about how big, and what
it holds), tick boxes to leave out the log or the settings, and the comment it needs (what you were doing when the
problem happened). show() gives (comment, leave_out), or None for Cancel.

`list_contents(leave_out)` gives the report's items (user/bug_report.contents for the open vault), so the list shown
is the one the report is made from.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import bug_report_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button

LOG, SETTINGS = "log", "settings"           # user/bug_report.LOG and SETTINGS


class BugReportDialog(modal_dialog.ModalDialog):
    FOCUS = "comment"

    def __init__(self, parent, address, problems=0, list_contents=None, taken_out="", never_in=""):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.list_contents = list_contents or (lambda leave_out: [])
        width, height = 640, 760
        self.wrap = width - 120                 # inside the list: its padding, the indent and the scroll bar
        self.title("Report a problem")
        window_chrome.place_over(self, parent, width, height)
        window_chrome.min_size(self, 500, 560)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=2)
        self.rowconfigure(8, weight=1)
        ctk.CTkLabel(self, text="Report a problem", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text=bug_report_text.intro(address, problems), anchor="w", justify="left",
                     wraplength=width - 40, text_color=theme.MUTED).grid(row=1, column=0, sticky="ew", padx=20)
        ctk.CTkLabel(self, text=bug_report_text.CONTENTS_HEADING, font=ctk.CTkFont(weight="bold"), anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(12, 2))
        self.items = ctk.CTkScrollableFrame(self, fg_color=theme.BG_PANEL)
        self.items.grid(row=3, column=0, sticky="nsew", padx=20)
        self.items.columnconfigure(0, weight=1)
        self.include_log = tk.BooleanVar(master=self, value=True)
        self.include_settings = tk.BooleanVar(master=self, value=True)
        for row, (text, variable) in enumerate(((bug_report_text.INCLUDE_LOG, self.include_log),
                                                (bug_report_text.INCLUDE_SETTINGS, self.include_settings)), start=4):
            ctk.CTkCheckBox(self, text=text, variable=variable, command=self._show_items).grid(
                row=row, column=0, sticky="w", padx=20, pady=(6, 0))
        ctk.CTkLabel(self, text=f"{taken_out} {never_in}".strip(), anchor="w", justify="left",
                     wraplength=width - 40, text_color=theme.MUTED).grid(row=6, column=0, sticky="ew", padx=20,
                                                                          pady=(8, 0))
        ctk.CTkLabel(self, text=bug_report_text.PROMPT + ":", anchor="w").grid(
            row=7, column=0, sticky="ew", padx=20, pady=(12, 2))
        self.comment = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, wrap="word", height=90,
                                      font=ctk.CTkFont(size=13))
        self.comment.grid(row=8, column=0, sticky="nsew", padx=20)
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=9, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=10, column=0, sticky="ew", padx=20, pady=(4, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Make the report", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._confirm).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self._show_items()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def leave_out(self):
        """What the tick boxes leave out: LOG and/or SETTINGS."""
        return tuple(group for group, variable in ((LOG, self.include_log), (SETTINGS, self.include_settings))
                     if not variable.get())

    def _show_items(self):
        """List the files the report would hold with the tick boxes as they are."""
        for child in self.items.winfo_children():
            child.destroy()
        for row, item in enumerate(self.list_contents(self.leave_out())):
            ctk.CTkLabel(self.items, text=bug_report_text.item_heading(item), font=ctk.CTkFont(weight="bold"),
                         anchor="w").grid(row=2 * row, column=0, sticky="ew", padx=8, pady=(6, 0))
            ctk.CTkLabel(self.items, text=item.what, anchor="w", justify="left", wraplength=self.wrap,
                         text_color=theme.MUTED).grid(row=2 * row + 1, column=0, sticky="ew", padx=(20, 8))

    def _confirm(self):
        comment = self.comment.get("1.0", "end").strip()
        if not comment:
            self.problem.configure(text=bug_report_text.NEEDS_COMMENT)
            return
        self.result = (comment, self.leave_out())
        self.destroy()
