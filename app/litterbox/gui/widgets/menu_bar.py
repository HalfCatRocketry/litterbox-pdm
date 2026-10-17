"""
menu_bar.py - the window's menu bar (File, Vault, View, Help on the left; the Litterbox logo and name on the
right), the dark drop-down menus it and the toolbar use, and DropButton, a toolbar button that opens a menu.

Windows' own menu bar can't put anything on the right or follow the dark theme, so this one is made of flat buttons
that each open a Tk menu. A menu's entries are filled in just before it opens, so what is greyed out is always
up to date.
"""

import tkinter as tk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import ui_scale
from litterbox.gui.widgets import release_button


def dark_menu(parent):
    """An empty Tk menu in the window's colours, with text at the window's scale."""
    scale = scaling.scale_of(parent)
    return tk.Menu(parent, tearoff=0, bg="#2b2b2b", fg=theme.TEXT, activebackground=theme.ACCENT,
                   activeforeground="#ffffff", disabledforeground="#6f6f6f", bd=0, relief="flat",
                   font=scaling.font(ui_scale.MENU_FONT, scale))


def open_below(menu, widget):
    """Show a menu just under a widget."""
    try:
        menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
    finally:
        try:
            menu.grab_release()
        except Exception:
            pass


class MenuBar(ctk.CTkFrame):
    """menus: [(title, fill)] where fill(menu) adds the entries each time the menu opens."""

    def __init__(self, master, menus, logo=None):
        super().__init__(master, fg_color=theme.BG_BAR, corner_radius=0, height=30)
        self.columnconfigure(len(menus), weight=1)
        self.buttons = {}
        for column, (title, fill) in enumerate(menus):
            button = ctk.CTkButton(self, text=title, width=0, height=26, corner_radius=4, fg_color="transparent",
                                   hover_color=theme.BG_HOVER, text_color=theme.TEXT,
                                   command=lambda title=title, fill=fill: self.open(title, fill))
            button.grid(row=0, column=column, padx=(6 if column == 0 else 0, 2), pady=2)
            self.buttons[title] = button
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=len(menus) + 1, sticky="e", padx=(0, 10))
        self.logo_label = tk.Label(brand, image=logo, bg=theme.BG_BAR, bd=0) if logo is not None else None
        if self.logo_label is not None:
            self.logo_label.grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(brand, text="Litterbox", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=theme.TEXT).grid(row=0, column=1)

    def set_logo(self, image):
        if self.logo_label is not None and image is not None:
            self.logo_label.configure(image=image)

    def open(self, title, fill):
        menu = dark_menu(self)
        fill(menu)
        open_below(menu, self.buttons[title])


class DropButton(release_button.ReleaseButton):
    """A toolbar button with a menu under it ("Open ▾"). fill(menu) adds the entries each time it opens."""

    def __init__(self, master, text, fill, **options):
        self.fill = fill
        super().__init__(master, text=f"{text}  ▾", command=self._open, **options)

    def _open(self):
        menu = dark_menu(self)
        self.fill(menu)
        open_below(menu, self)
