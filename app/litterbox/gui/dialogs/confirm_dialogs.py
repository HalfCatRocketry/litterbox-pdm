"""
confirm_dialogs.py - "Are you sure?" windows: ConfirmDialog (a heading and lines to read before going
ahead) and DiscardDialog (discard unsaved changes?).
"""


import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class DiscardDialog(modal_dialog.ModalDialog):
    """'Discard changes?' with Discard and Keep editing. Use ask_discard(parent, what)."""

    def __init__(self, parent, what):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.discard = False
        width, height = 420, 170
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title("Discard changes?")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure((0, 1), weight=1, uniform="d")
        ctk.CTkLabel(self, text=f"Discard {what}?", font=ctk.CTkFont(size=15, weight="bold"), anchor="w",
                     wraplength=380, justify="left").grid(row=0, column=0, columnspan=2, sticky="ew", padx=20,
                                                          pady=(20, 4))
        ctk.CTkLabel(self, text="This can't be undone.", text_color=theme.MUTED, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=20)
        release_button.ReleaseButton(self, text="Keep editing", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=2, column=0, sticky="ew", padx=(20, 6), pady=22)
        release_button.ReleaseButton(self, text="Discard", height=38, fg_color=theme.RED, hover_color=theme.RED_HOVER,
                      command=self._discard).grid(row=2, column=1, sticky="ew", padx=(6, 20), pady=22)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _discard(self):
        self.discard = True
        self.destroy()

    def show(self):
        self.wait_window(self)
        return self.discard


def ask_discard(parent, what="these changes"):
    """True if the user chose Discard, False for Keep editing (or closing the question)."""
    return DiscardDialog(parent, what).show()


class ConfirmDialog(modal_dialog.ModalDialog):
    """A small pop-up: a heading, a list of lines, an optional note, and Cancel / Continue buttons.

        dialog = ConfirmDialog(parent, "Title", "Heading", ["line 1", "line 2"], note="...")
        if dialog.show():        # True if the user pressed the confirm button
            ...
    """

    def __init__(self, parent, title, heading, lines, note="", confirm_text="Continue"):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = False
        width, height = 540, 420
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 3, 0)
        self.title(title)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.resizable(False, False)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ctk.CTkLabel(self, text=heading, font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
                     justify="left", wraplength=width - 40).grid(
            row=0, column=0, sticky="ew", padx=20, pady=(20, 8))

        box = ctk.CTkTextbox(self, fg_color=theme.BG_PANEL, font=ctk.CTkFont(family="Consolas", size=13))
        box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8))
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")

        if note:
            ctk.CTkLabel(self, text=note, text_color=theme.MUTED, anchor="w", justify="left",
                         wraplength=width - 40).grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text=confirm_text, height=38, fg_color=theme.GREEN, hover_color=theme.GREEN_HOVER,
                      command=self._confirm).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda event: self._cancel())
        self.after(150, self._grab)         # make the pop-up modal once it is on screen

    def _confirm(self):
        self.result = True
        self.destroy()

    def _cancel(self):
        self.destroy()
