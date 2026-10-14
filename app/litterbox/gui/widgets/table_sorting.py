"""
table_sorting.py - the look of every table (ttk.Treeview) and click-a-heading-to-sort (TableSorter).
"""

from tkinter import ttk

from litterbox.gui import theme
from litterbox.gui.logic import list_view


def style_tables():
    """Make the plain Tk table (Treeview) match the dark theme."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Treeview", background=theme.BG_PANEL, foreground="#e6e6e6", fieldbackground=theme.BG_PANEL,
        borderwidth=0, rowheight=30, font=("Segoe UI", 10),
    )
    style.configure(
        "Treeview.Heading", background="#1f1f1f", foreground="#e6e6e6",
        relief="flat", font=("Segoe UI", 10, "bold"), padding=6,
    )
    style.map("Treeview", background=[("selected", theme.ACCENT)])
    style.map("Treeview.Heading", background=[("active", "#333333")])
    # The parts list: one blue highlighted row (for looking at a part), and lighter gray for rows with a box ticked.
    style.configure("Parts.Treeview", background=theme.BG_PANEL, foreground="#e6e6e6", fieldbackground=theme.BG_PANEL,
                    borderwidth=0, rowheight=30, font=("Segoe UI", 10))
    style.map("Parts.Treeview", background=[("selected", theme.ACCENT)])
    style.layout("Parts.Treeview", style.layout("Treeview"))


class TableSorter:
    """Click a column heading to sort a table by it; click again to reverse. ▲ / ▼ shows the sort.

        sorter = TableSorter(tree, [("pn", "Part number"), ...])
        ...after the table is redrawn...
        sorter.apply()
    Numbers inside text sort as numbers, capitals are ignored, and blanks always go last.
    """

    def __init__(self, tree, titles):
        self.tree, self.titles = tree, list(titles)
        self.column, self.reverse = None, False
        for name, title in self.titles:
            self.tree.heading(name, text=title, anchor="w", command=lambda name=name: self.click(name))

    def click(self, column):
        self.reverse = (not self.reverse) if column == self.column else False
        self.column = column
        self.apply()

    def apply(self):
        """Show the arrow, and put the rows in order (call again after the rows are redrawn)."""
        for name, title in self.titles:
            arrow = (" ▼" if self.reverse else " ▲") if name == self.column else ""
            self.tree.heading(name, text=title + arrow)
        if self.column is None:
            return
        ids = list(self.tree.get_children())
        values = [self.tree.set(iid, self.column) for iid in ids]
        for position, index in enumerate(list_view.sort_order(values, self.reverse)):
            self.tree.move(ids[index], "", position)
