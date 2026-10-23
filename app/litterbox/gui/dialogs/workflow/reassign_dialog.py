"""
reassign_dialog.py - giving a sign-off slot to someone else: any open one (All Workflows' Change signer...), or
one of your own from the Review window.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class ReassignDialog(modal_dialog.ModalDialog):
    """Change who signs a sign-off that hasn't been given. show() gives (slot index, person id) or None.
    With `only` (a slot index), it is that sign-off, and `exclude` (person ids) are left out of the choices."""

    def __init__(self, parent, task, directory, requester_may_sign=True, only=None, exclude=()):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.task, self.directory, self.exclude = None, task, directory, set(exclude)
        self.open = [(i, s) for i, s in enumerate(task.slots) if not s["done"] and (only is None or i == only)]
        width, height = 520, 260
        heading = "Reassign your sign-off" if only is not None else "Change who signs"
        self.title(heading)
        window_chrome.place_over(self, parent, width, height)
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        self.slot_labels = {f"{s['text']}  (now {s['name']})": i for i, s in self.open}
        self.slot_var = tk.StringVar(value=next(iter(self.slot_labels)))
        ctk.CTkOptionMenu(self, variable=self.slot_var, values=list(self.slot_labels), width=470, fg_color=theme.GRAY,
                          button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                          command=lambda value: self._people()).grid(row=1, column=0, padx=20, sticky="w")
        self.person_var = tk.StringVar()
        self.person_menu = ctk.CTkOptionMenu(self, variable=self.person_var, values=[""], width=470, fg_color=theme.GRAY,
                                             button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT)
        self.person_menu.grid(row=2, column=0, padx=20, pady=(8, 0), sticky="w")
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(8, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="OK", height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._ok).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.ids = {}
        self._people()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(150, self._grab)

    def _people(self):
        index = self.slot_labels[self.slot_var.get()]
        choices = [(label, pid) for label, pid in task_text.row_choices(self.directory, self.task.slots[index]["roles"])
                   if pid not in self.exclude]
        self.ids = {label: pid for label, pid in choices}
        self.person_menu.configure(values=[label for label, _ in choices] or ["(nobody holds the role)"])
        self.person_var.set(choices[0][0] if choices else "(nobody holds the role)")

    def _ok(self):
        pid = self.ids.get(self.person_var.get())
        if not pid:
            self.problem.configure(text="Choose a person.")
            return
        self.result = (self.slot_labels[self.slot_var.get()], pid)
        self.destroy()
