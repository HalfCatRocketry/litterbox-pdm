"""
superuser_sign_dialog.py - a superuser reviewing a request and ticking the sign-offs they give for others.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import task_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class SuperuserSignDialog(modal_dialog.ModalDialog):
    """Show a request (its parts, who has signed, the reason and ECO) and tick which of its open sign-offs to give
    as a superuser; all are ticked to start with. show() gives (slot indices, comment) or None."""

    def __init__(self, parent, task):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.task = None, task
        width, height = 560, 300 + 34 * len(task.superuser_slots)
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(f"Approve as superuser: {task.label}")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(440, 260)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Approve as superuser", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        ctk.CTkLabel(self, text=task_text.task_detail(task), anchor="w", justify="left", wraplength=500).grid(
            row=1, column=0, sticky="ew", padx=20)
        ctk.CTkLabel(self, text="Sign for:", text_color=theme.MUTED, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(12, 2))
        boxes = ctk.CTkFrame(self, fg_color="transparent")
        boxes.grid(row=3, column=0, sticky="ew", padx=20)
        self.ticks = {}
        for number, index in enumerate(task.superuser_slots):
            var = tk.BooleanVar(value=True)
            ctk.CTkCheckBox(boxes, text=task_text.superuser_slot_text(task.slots[index]), variable=var).grid(
                row=number, column=0, sticky="w", pady=3)
            self.ticks[index] = var
        self.comment = ctk.CTkEntry(self, height=34, placeholder_text="Comment (optional)")
        self.comment.grid(row=4, column=0, sticky="ew", padx=20, pady=(10, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=6, column=0, sticky="ew", padx=20, pady=(6, 16))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Approve ticked", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._ok).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _ok(self):
        chosen = [index for index, var in self.ticks.items() if var.get()]
        if not chosen:
            self.problem.configure(text="Tick at least one sign-off to give.")
            return
        self.result = (chosen, " ".join(self.comment.get().split()))
        self.destroy()
