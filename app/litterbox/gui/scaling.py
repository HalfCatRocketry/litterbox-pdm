"""
scaling.py - making the plain Tk parts of the window (tables, menus, tooltips, icons) follow the display's
scaling the way CustomTkinter's own widgets do. The sizes themselves are in gui/logic/ui_scale.py.

Without this, Tk draws its tables at 100% even on a 150% screen: the rows and text come out a third smaller than
the buttons around them.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui.logic import ui_scale

FONT_FAMILY = "Segoe UI"


def scale_of(widget):
    """How much bigger than 100% to draw things in this widget's window: the monitor's scaling times the Text size.
    1.0 if it can't be told (no window yet, or not Windows)."""
    try:
        value = float(ctk.ScalingTracker.get_widget_scaling(widget))
        return value if value > 0 else 1.0
    except Exception:
        return 1.0


def font(size, scale, weight="normal"):
    """A Tk font description at this scale (size in pixels at 100%)."""
    return (FONT_FAMILY, ui_scale.font_px(size, scale), weight) if weight != "normal" else \
        (FONT_FAMILY, ui_scale.font_px(size, scale))


def style_tables(scale=1.0):
    """Make every table (ttk.Treeview) match the dark theme at this scale. The parts list has its own style,
    Parts.Treeview, whose first column holds pictures but no tree lines."""
    style = ttk.Style()
    style.theme_use("clam")
    row = ui_scale.px(ui_scale.TABLE_ROW, scale)
    body = font(ui_scale.TABLE_FONT, scale)
    for name in ("Treeview", "Parts.Treeview"):
        style.configure(name, background=theme.BG_PANEL, foreground=theme.TEXT, fieldbackground=theme.BG_PANEL,
                        borderwidth=0, rowheight=row, font=body)
        style.map(name, background=[("selected", theme.ACCENT)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=theme.BG_HEADING, foreground=theme.TEXT, relief="flat",
                    font=font(ui_scale.TABLE_HEADING_FONT, scale, "bold"),
                    padding=(ui_scale.px(6, scale), ui_scale.px(5, scale)))
    style.map("Treeview.Heading", background=[("active", "#333333")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])      # no border round the rows
    style.layout("Parts.Treeview", style.layout("Treeview"))
    style.configure("Parts.Treeview", indent=0)
    try:                                    # no expand arrows in the parts list: its rows have no children
        style.layout("Parts.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.focus", {"side": "left", "sticky": "", "children": [
                ("Treeitem.text", {"side": "left", "sticky": ""})]})]})])
    except Exception:
        pass
    style.configure("TPanedwindow", background=theme.BG)
    style.configure("Sash", sashthickness=ui_scale.px(6, scale), gripcount=0, background=theme.BG)


def watch(widget, callback):
    """Call callback() whenever the window's scaling changes (moved to another monitor, or Text size changed)."""
    try:
        ctk.ScalingTracker.add_widget(lambda *_args: callback(), widget)
    except Exception:
        pass


def set_text_size(percent):
    """Make every CustomTkinter widget this much bigger than Windows' own scaling (View > Text size)."""
    try:
        ctk.set_widget_scaling(percent / 100)
    except Exception:
        pass
