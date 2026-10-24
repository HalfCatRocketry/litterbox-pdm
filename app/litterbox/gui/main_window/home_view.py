"""
home_view.py - Home: the folders view of the parts screen (folders/), switched with Vault (the parts list) by the
Home / Vault switch above the list. Three tops, Personal, Team and Projects (a top per project of yours), each a
tree of folders; a folder lists what it points at, one line each: a tick box, the number, the name.

A tick here is the same tick as in the Vault list (the window's `ticked`), so the toolbar's actions work on what is
ticked in Home; clicking an item shows its details, like a row of the parts list. What the folders say is worked
out in gui/logic/folder_text.py; changing them (menus, dragging) is home_actions.py.
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.folders import folder_access
from litterbox.folders import personal_folders
from litterbox.folders.folder_store import Trees
from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import folder_text
from litterbox.gui.logic import ui_scale
from litterbox.gui.widgets import tooltip
from litterbox.user import settings

HOME, VAULT = "Home", "Vault"


class HomeView:
    """Home, beside the parts list. One part of the main window (App)."""

    home_shown = False
    home_trees = Trees()
    home_projects = ()
    home_personal = {}
    home_rows = {}              # iid -> folder_text.HomeRow, for what is drawn now
    eco_titles = {}             # ECO number -> its title, for ECOs in folders

    # -- building ----------------------------------------------------------------------------------------------
    def _build_view_switch(self, parent):
        """The Home / Vault switch above the list."""
        self.view_switch = ctk.CTkSegmentedButton(parent, values=[HOME, VAULT], height=32,
                                                  command=lambda value: self.show_home(value == HOME))
        self.view_switch.set(VAULT)
        tooltip.Tooltip(self.view_switch, "Home: your folders, the Team's and your projects'. Vault: every part.")
        return self.view_switch

    def _build_home(self, parent):
        """Home's tree, in the same place as the parts list (shown instead of it)."""
        frame = self.home_frame = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=8)
        frame.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.home = ttk.Treeview(frame, show="tree", selectmode="browse")
        self.home.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        down = ctk.CTkScrollbar(frame, command=self.home.yview)
        down.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 2))
        self.home.configure(yscrollcommand=down.set)
        self.home.bind("<Button-1>", self._on_home_press, add="+")
        self.home.bind("<B1-Motion>", self._on_home_drag, add="+")
        self.home.bind("<ButtonRelease-1>", self._on_home_drop, add="+")
        self.home.bind("<Button-3>", self._on_home_right_click, add="+")
        self.home.bind("<Double-1>", self._on_home_double_click, add="+")
        self.home.bind("<space>", lambda event: self._tick_home_selection())
        self.home.bind("<<TreeviewSelect>>", lambda event: self._selection_changed(), add="+")
        for kind, color in theme.ROW_COLORS.items():
            self.home.tag_configure(kind, foreground=color)
        self.home.tag_configure("top", font=scaling.font(ui_scale.TABLE_FONT, self.scale, "bold"))
        frame.grid_remove()
        if settings_choice(getattr(self, "settings", {})) == HOME:
            self.after(0, lambda: self.show_home(True))

    # -- showing -----------------------------------------------------------------------------------------------
    def show_home(self, on):
        """Show Home (True) or the Vault list (False), and remember the choice."""
        self.home_shown = bool(on)
        self.view_switch.set(HOME if on else VAULT)
        if on:
            self.list_frame.grid_remove()
            self.home_frame.grid()
            self._load_personal()
            self._render_home()
        else:
            self.home_frame.grid_remove()
            self.list_frame.grid()
            self._render()
        for widget in (self.search_in_menu, self.columns_button):
            widget.configure(state="disabled" if on else "normal")
        if self.settings.get("list_view") != (HOME if on else VAULT):
            self.settings["list_view"] = HOME if on else VAULT
            settings.save(self.settings)
        self._selection_changed()

    def personal_path(self):
        """Where this org's Personal folders are kept on this computer."""
        return settings.ROOT / "folders" / f"{self.org or 'none'}.yaml"

    def _load_personal(self):
        self.home_personal = personal_folders.load(self.personal_path())

    def _describe_item(self, item):
        """An item's name, for its line in Home ("" if this vault doesn't know it)."""
        kind, number = folder_text.parse_item(item)
        if kind in ("part", "document"):
            row = self.rows_by_pn.get(number)
            return row.name if row is not None else ""
        if kind == "eco":
            return self.eco_titles.get(number, "")
        return ""

    def _item_tags(self, row):
        kind, number = folder_text.parse_item(row.item)
        part = self.rows_by_pn.get(number) if kind in ("part", "document") else None
        return (part.kind,) if part is not None else ()

    def _render_home(self):
        """Draw Home again from the folders as last loaded, keeping what is open and highlighted."""
        if not getattr(self, "home", None):
            return
        tree = self.home
        opened = {iid for iid in self.home_rows if tree.exists(iid) and tree.item(iid, "open")}
        first_time = not self.home_rows
        chosen = set(tree.selection())
        tree.delete(*tree.get_children())
        projects = folder_access.shown_projects(self.identity, self.home_projects)
        rows = folder_text.home_rows(self.home_personal, self.home_trees, projects, self._describe_item,
                                     self.search.get() if self.home_shown else "")
        self.home_rows = {row.iid: row for row in rows}
        size = self._px(ui_scale.ICON)
        searching = bool(self.search.get().strip())
        for row in rows:
            if row.kind == "item":
                image = self.icons.tick(size, row.item in self.ticked)
                tags = self._item_tags(row)
            else:
                name = {folder_text.PERSONAL_TITLE: "folder", folder_text.TEAM_TITLE: "team",
                        folder_text.PROJECTS_TITLE: "list"}.get(row.text, "folder") if row.kind == "top" else "folder"
                image = self.icons.icon(name, size, theme.MUTED)
                tags = ("top",) if row.kind == "top" else ()
            is_open = searching or row.iid in opened or (first_time and row.kind == "top")
            tree.insert(row.parent, "end", iid=row.iid, text=f"  {row.text}", image=image, tags=tags, open=is_open)
        if projects == [] and tree.exists("top:projects"):
            tree.item("top:projects", text=f"  {folder_text.PROJECTS_TITLE}   (none of yours yet)")
        keep = [iid for iid in chosen if tree.exists(iid)]
        if keep:
            tree.selection_set(*keep)
        self._update_buttons()

    # -- ticks and the highlight -------------------------------------------------------------------------------
    def _home_item_numbers(self):
        """Every part or document Home lists, as {text: PN or DocNumber}."""
        found = {}
        for row in self.home_rows.values():
            if row.kind == "item":
                kind, number = folder_text.parse_item(row.item)
                if kind in ("part", "document") and number in self.rows_by_pn:
                    found[row.item] = number
        return found

    def _home_ticked(self):
        """The ticked parts and documents Home lists (each once)."""
        listed = self._home_item_numbers()
        return [number for text, number in listed.items() if text in self.ticked]

    def _home_highlighted(self):
        """The part or document highlighted in Home ([] for a folder, an ECO or nothing)."""
        chosen = self.home.selection()
        row = self.home_rows.get(chosen[0]) if chosen else None
        if row is None or row.kind != "item":
            return []
        kind, number = folder_text.parse_item(row.item)
        return [number] if kind in ("part", "document") and number in self.rows_by_pn else []

    def _set_home_ticks(self, items, on):
        """Tick (or untick) these items everywhere they appear, in Home and in the Vault list."""
        items = [str(item) for item in items]
        self._set_ticks(items, on)
        size = self._px(ui_scale.ICON)
        for iid, row in self.home_rows.items():
            if row.kind == "item" and row.item in items and self.home.exists(iid):
                self.home.item(iid, image=self.icons.tick(size, on))

    def _tick_home_selection(self):
        chosen = self.home.selection()
        row = self.home_rows.get(chosen[0]) if chosen else None
        if row is not None and row.kind == "item":
            self._set_home_ticks([row.item], row.item not in self.ticked)
        return "break"

    def _on_home_press(self, event):
        """A click on an item's tick box flips it (and isn't the start of a drag)."""
        iid = self.home.identify_row(event.y)
        row = self.home_rows.get(iid)
        self._drag = None
        if row is None:
            return None
        if row.kind == "item" and "image" in str(self.home.identify_element(event.x, event.y)):
            self._set_home_ticks([row.item], row.item not in self.ticked)
            return "break"
        self._drag = {"source": iid, "x": event.x, "y": event.y, "moved": False}
        return None


def settings_choice(data):
    """Home or Vault, as last chosen (Vault to start with)."""
    return HOME if (data or {}).get("list_view") == HOME else VAULT
