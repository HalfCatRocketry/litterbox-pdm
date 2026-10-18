"""
text_input.py - asking for one line of text (InputDialog) or a reason (ReasonDialog).
"""


import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class InputDialog(ctk.CTkInputDialog):
    """The one-line text prompt, with the Litterbox icon."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        window_chrome.set_window_icon(self)


class ReasonDialog(modal_dialog.ModalDialog):
    """A question with a message and a required one-line reason.

        reason = ReasonDialog(parent, "Revise HCR-00001-001", "text...", "Why is it being revised?", "Revise").show()
        # None if cancelled, else the reason (never blank)
    """
    FOCUS = "entry"

    def __init__(self, parent, title, message, label, confirm_text="OK"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 540, 440
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        box = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, wrap="word", font=ctk.CTkFont(size=13))
        box.grid(row=0, column=0, sticky="nsew", padx=20, pady=(20, 8))
        box.insert("1.0", message)
        box.configure(state="disabled")
        ctk.CTkLabel(self, text=label, anchor="w").grid(row=1, column=0, sticky="ew", padx=20)
        self.entry = ctk.CTkEntry(self, height=34)
        self.entry.grid(row=2, column=0, sticky="ew", padx=20, pady=(2, 0))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=3, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text=confirm_text, height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._confirm).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.bind("<Return>", lambda event: self._confirm())
        self.after(150, self._grab)

    def _confirm(self):
        reason = " ".join(self.entry.get().split())
        if not reason:
            self.problem.configure(text="A reason is required.")
            return
        self.result = reason
        self.destroy()
