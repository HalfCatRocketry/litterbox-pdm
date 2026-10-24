"""
toolbox_dialog.py - Team > Toolbox...: the team's SolidWorks Toolbox (vault/toolbox_admin.py), for everyone to look
at and download; Admins and the Owner can also copy a Toolbox folder in, make it changeable, and upload changes.
show() gives the button pressed, as (action, folder): ("download", None), ("copy_in", folder), ("open", None),
("upload", None), or None for Close. The main window does the work (gui/main_window/team_admin.py).
"""

from tkinter import filedialog

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import toolbox_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class ToolboxDialog(modal_dialog.ModalDialog):
    def __init__(self, parent, status, admin):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.status = None, status
        width, height = 760, 470
        self.title("Toolbox")
        window_chrome.place_over(self, parent, width, height, down=4)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="The team's Toolbox", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        ctk.CTkLabel(self, text="\n".join(toolbox_text.status_lines(status, admin)), anchor="nw", justify="left",
                     wraplength=width - 50).grid(row=1, column=0, sticky="nsew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=20, pady=(14, 16))
        entries = [("Download", "download", bool(status.not_downloaded))]
        if admin:
            entries += [("Copy in a Toolbox folder...", "copy_in", True),
                        ("Let me change it", "open", bool(status.files)),
                        ("Upload changes", "upload", status.has_changes)]
        for column, (text, action, usable) in enumerate(entries):
            release_button.ReleaseButton(buttons, text=text, height=34, width=100, fg_color=theme.ACCENT,   # as wide as its text
                                         state="normal" if usable else "disabled",
                                         command=lambda a=action: self._choose(a)).grid(
                row=0, column=column, sticky="w", padx=(0, 8))
        release_button.ReleaseButton(buttons, text="Close", height=34, width=80, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=len(entries), sticky="e")
        buttons.columnconfigure(len(entries), weight=1)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _choose(self, action):
        folder = None
        if action == "copy_in":
            folder = filedialog.askdirectory(parent=self, title="The Toolbox folder to copy in (C:\\SOLIDWORKS Data)",
                                             mustexist=True)
            if not folder:
                return
        self.result = (action, folder)
        self.destroy()
