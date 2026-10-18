"""
nav_item.py - NavItem: one entry in the main window's sidebar (an icon, a name and a count). Click it to show
that list or screen. When the sidebar is narrow only the icon shows, and the name moves to a tooltip.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.widgets import tooltip


class NavItem(ctk.CTkFrame):
    def __init__(self, master, text, command, images=(None, None)):
        """images: (the icon normally, the icon when this entry is the one showing)."""
        super().__init__(master, fg_color="transparent", corner_radius=6, height=34)
        self.text, self.command, self.images = text, command, images
        self.chosen, self.collapsed, self.count = False, False, None
        self.columnconfigure(1, weight=1)
        self.icon = tk.Label(self, image=images[0], bg=theme.BG_SIDEBAR, bd=0, cursor="hand2")
        self.icon.grid(row=0, column=0, padx=(10, 8), pady=5)
        self.label = ctk.CTkLabel(self, text=text, anchor="w", text_color=theme.MUTED, cursor="hand2")
        self.label.grid(row=0, column=1, sticky="ew")
        self.count_label = ctk.CTkLabel(self, text="", anchor="e", text_color=theme.MUTED, cursor="hand2",
                                        font=ctk.CTkFont(size=12))
        self.count_label.grid(row=0, column=2, sticky="e", padx=(4, 10))
        for widget in (self, self.icon, self.label, self.count_label):
            widget.bind("<Button-1>", lambda event: self.command(), add="+")
            widget.bind("<Enter>", lambda event: self._paint(hover=True), add="+")
            widget.bind("<Leave>", lambda event: self._paint(), add="+")
        tooltip.Tooltip(self.icon, lambda: self.text if self.collapsed else "")

    def _paint(self, hover=False):
        background = theme.BG_CHOSEN if self.chosen else (theme.BG_HOVER if hover else theme.BG_SIDEBAR)
        self.configure(fg_color=background)
        self.icon.configure(bg=background, image=self.images[1 if self.chosen else 0])
        self.label.configure(text_color=theme.TEXT if self.chosen else theme.MUTED)

    def set_images(self, images):
        self.images = images
        self._paint()

    def set_chosen(self, chosen):
        self.chosen = chosen
        self._paint()

    def set_count(self, count):
        """A number after the name ('' or None hides it)."""
        self.count = count
        self.count_label.configure(text="" if count in (None, "") else str(count))

    def set_collapsed(self, collapsed):
        self.collapsed = collapsed
        if collapsed:
            self.label.grid_remove()
            self.count_label.grid_remove()
            self.icon.grid_configure(padx=(10, 10))
        else:
            self.label.grid()
            self.count_label.grid()
            self.icon.grid_configure(padx=(10, 8))
