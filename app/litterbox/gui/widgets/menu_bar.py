"""
menu_bar.py - the window's menu bar (File, Vault, View, Help on the left; the open org's name in the middle; the
Litterbox logo and name on the right), the dark drop-down menus it and the toolbar use, and DropButton, a toolbar button that opens a menu.

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


ALT_KEYS = {"File": "f", "Vault": "a", "View": "v", "Help": "h"}      # Alt+F opens File, and so on

MENU_BG = "#2b2b2b"
GREYED_FG = "#6f6f6f"


def dark_menu(parent):
    """An empty Tk menu in the window's colours, with text at the window's scale."""
    scale = scaling.scale_of(parent)
    return tk.Menu(parent, tearoff=0, bg=MENU_BG, fg=theme.TEXT, activebackground=theme.ACCENT,
                   activeforeground="#ffffff", disabledforeground=GREYED_FG, bd=0, relief="flat",
                   font=scaling.font(ui_scale.MENU_FONT, scale))


def entry_options(usable, command=None):
    """The options for a menu entry: its command when usable, else greyed out. Tk on Windows draws a disabled entry
    etched (a white copy of the text under the grey one), which looks blurred on a dark menu, so a greyed-out entry
    is left enabled but coloured grey, doesn't light up under the mouse, and does nothing."""
    if usable:
        return {} if command is None else {"command": command}
    return {"foreground": GREYED_FG, "activeforeground": GREYED_FG, "activebackground": MENU_BG,
            "command": lambda: None}


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
    """menus: [(title, fill)] where fill(menu) adds the entries each time the menu opens. Alt and a menu's key
    opens it (see ALT_KEYS). set_title shows a name centred on the bar (the open org's), hidden when the window is
    too narrow for it to fit between the menus and the logo."""

    TITLE_GAP = 16                  # room kept either side of the centred name, at 100%

    def __init__(self, master, menus, logo=None):
        super().__init__(master, fg_color=theme.BG_BAR, corner_radius=0, height=30)
        self.columnconfigure(len(menus), weight=1)
        self.buttons, self.fills = {}, dict(menus)
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
        self.brand = brand
        self.title_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=14, weight="bold"),
                                        text_color=theme.TEXT)
        self.bind("<Configure>", lambda event: self._place_title(), add="+")

    def set_title(self, text):
        """The name in the middle of the bar ('' hides it)."""
        self.title_label.configure(text=text or "")
        self._place_title()

    def _place_title(self):
        """Centred on the bar, unless it would run into the menus or the logo."""
        if not self.title_label.cget("text"):
            self.title_label.place_forget()
            return
        try:
            width = self.winfo_width()
            menus = max(b.winfo_x() + b.winfo_width() for b in self.buttons.values()) if self.buttons else 0
            brand = self.brand.winfo_x() if self.brand.winfo_ismapped() else width
            half = self.title_label.winfo_reqwidth() / 2 + self.TITLE_GAP * scaling.scale_of(self)
        except Exception:
            return
        if width <= 1 or brand <= menus:                   # not laid out yet: look again in a moment
            self.after(100, self._place_title)
            return
        if width / 2 - half < menus or width / 2 + half > brand:
            self.title_label.place_forget()
        else:
            self.title_label.place(relx=0.5, rely=0.5, anchor="center")

    def set_logo(self, image):
        if self.logo_label is not None and image is not None:
            self.logo_label.configure(image=image)

    def open_named(self, title):
        """Open a menu from the keyboard (Alt and its key)."""
        if title in self.fills:
            self.open(title, self.fills[title])

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
