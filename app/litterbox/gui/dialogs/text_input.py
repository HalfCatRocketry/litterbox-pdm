"""
text_input.py - asking for one line of text (InputDialog), a reason (ReasonDialog), or the comment for a list of
things (CommentDialog: Check In and Save Progress).
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
        self.title(title)
        window_chrome.place_over(self, parent, width, height)
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


class CommentDialog(modal_dialog.ModalDialog):
    """A one-line comment about a list of things, shown above it (Check In: the parts being checked in). The
    comment may be left blank.

        comment = CommentDialog(parent, "Check In", "Check in these 2:", lines, note, "Describe your changes:",
                                "Check In").show()     # None if cancelled, else the comment ("" if left blank)
    """
    FOCUS = "entry"

    def __init__(self, parent, title, heading, lines, note, label, confirm_text="OK"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        width, height = 560, min(560, 300 + 22 * len(lines))
        self.title(title)
        window_chrome.place_over(self, parent, width, height)
        window_chrome.min_size(self, 420, 300)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 4))
        box = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, wrap="none", font=ctk.CTkFont(size=13))
        box.grid(row=1, column=0, sticky="nsew", padx=20)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")
        ctk.CTkLabel(self, text=note, text_color=theme.MUTED, justify="left", anchor="w", wraplength=width - 40).grid(
            row=2, column=0, sticky="ew", padx=20, pady=(6, 6))
        ctk.CTkLabel(self, text=label, anchor="w").grid(row=3, column=0, sticky="ew", padx=20)
        self.entry = ctk.CTkEntry(self, height=34)
        self.entry.grid(row=4, column=0, sticky="ew", padx=20, pady=(2, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(12, 18))
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
        self.result = " ".join(self.entry.get().split())
        self.destroy()
