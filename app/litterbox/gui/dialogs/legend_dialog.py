"""
legend_dialog.py - Help > Status icons: what each icon in the parts list means.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import status_icons
from litterbox.gui.logic import ui_scale
from litterbox.gui.widgets import release_button

SHAPE_COLOR = {shape: theme.ICON_COLORS.get(kind, theme.TEXT) for kind, (shape, _t, _x) in status_icons.STATUS.items()}
SHAPE_COLOR.update(busy=theme.ICON_COLORS["busy"], cloud=theme.ICON_COLORS["cloud"])


class LegendDialog(ctk.CTkToplevel):
    def __init__(self, parent, icons):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.title("Status icons")
        window_chrome.set_size(self, 560, 560)
        window_chrome.min_size(self, 420, 360)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="What the icons in the parts list mean", font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        body = ctk.CTkScrollableFrame(self, fg_color=theme.BG_PANEL)
        body.grid(row=1, column=0, sticky="nsew", padx=20)
        body.columnconfigure(1, weight=1)
        size = ui_scale.px(22, scaling.scale_of(self))
        for number, (shape, title, text) in enumerate(status_icons.legend()):
            image = icons.icon(shape, size, SHAPE_COLOR.get(shape, theme.TEXT))
            tk.Label(body, image=image, bg=theme.BG_PANEL, bd=0).grid(row=number, column=0, sticky="n", padx=(6, 12),
                                                                       pady=6)
            ctk.CTkLabel(body, text=f"{title}\n{text}", anchor="w", justify="left", wraplength=380).grid(
                row=number, column=1, sticky="w", pady=4)
        ctk.CTkLabel(self, text="Tick a part's box (left of its icon) to act on it. Rest the mouse on an icon to see "
                                "the part's full status.", text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=500).grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        release_button.ReleaseButton(self, text="Close", width=90, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                     command=self.destroy).grid(row=3, column=0, sticky="e", padx=20, pady=12)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(100, self.lift)
