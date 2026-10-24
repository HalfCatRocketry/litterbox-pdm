"""
sidebar.py - the sidebar on the left of the main window: the parts list's views (All, Mine, Checked out, ...) with
how many parts each has (under PARTS), then Workflows and ECO (under PROCESS) and Team, which are screens of their
own. On a narrow window it shows only the icons (View > Sidebar names switches the names back on).
"""

import customtkinter as ctk

from litterbox.change_orders import eco_store
from litterbox.gui import theme
from litterbox.gui.logic import list_view
from litterbox.gui.logic import ui_scale
from litterbox.gui.screens import eco_screen
from litterbox.gui.screens import documents_screen
from litterbox.gui.screens import tasks_screen
from litterbox.gui.screens import team_screen
from litterbox.gui.widgets import nav_item
from litterbox.gui.widgets import release_button
from litterbox.vault import project_visibility
from litterbox.workflows import workflow_tasks

# The parts list's views and their icons, then the other screens.
VIEW_ICONS = {"All": "list", "Mine": "pencil", "Checked out": "padlock", "Released": "check",
              "Not downloaded": "cloud", "Void": "ban"}


SCREENS = (("tasks", "Workflows", "tasks"), ("ecos", "ECOs", "document"), ("documents", "Documents", "list"))


NAV_ICON = 18                   # the sidebar's icons, at 100%


class Sidebar:
    """The sidebar and switching between screens. One part of the main window (App)."""

    def _nav_images(self, shape):
        size = self._px(NAV_ICON)
        return self.icons.icon(shape, size, theme.MUTED), self.icons.icon(shape, size, theme.TEXT)

    def _build_sidebar(self, parent):
        bar = self.sidebar = ctk.CTkFrame(parent, fg_color=theme.BG_SIDEBAR, corner_radius=0, width=190)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.columnconfigure(0, weight=1, minsize=self._px(176))
        self.parts_heading = ctk.CTkLabel(bar, text="PARTS", text_color=theme.MUTED, anchor="w",
                                          font=ctk.CTkFont(size=12, weight="bold"))
        self.parts_heading.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        self.nav = {}
        row = 1
        for view in list_view.VIEWS:
            item = nav_item.NavItem(bar, view, lambda view=view: self.set_view(view), self._nav_images(VIEW_ICONS[view]))
            item.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
            self.nav[("parts", view)] = item
            row += 1
        ctk.CTkFrame(bar, width=1, height=1, fg_color="#333333").grid(row=row, column=0, sticky="ew", padx=12, pady=8)
        row += 1
        self.process_heading = ctk.CTkLabel(bar, text="PROCESS", text_color=theme.MUTED, anchor="w",
                                            font=ctk.CTkFont(size=12, weight="bold"))
        self.process_heading.grid(row=row, column=0, sticky="ew", padx=14, pady=(0, 2))
        row += 1
        for screen, text, shape in SCREENS:
            item = nav_item.NavItem(bar, text, lambda screen=screen: self.show_screen(screen), self._nav_images(shape))
            item.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
            self.nav[(screen, None)] = item
            row += 1
        bar.rowconfigure(row, weight=1)
        row += 1
        item = nav_item.NavItem(bar, "Team", lambda: self.show_screen("team"), self._nav_images("team"))
        item.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
        self.nav[("team", None)] = item
        self.collapse_button = release_button.ReleaseButton(
            bar, text="«", width=32, height=26, fg_color="transparent", hover_color=theme.BG_HOVER,
            text_color=theme.MUTED, command=lambda: self.set_sidebar_collapsed(not self.sidebar_collapsed, chosen=True))
        self.collapse_button.grid(row=row + 1, column=0, sticky="w", padx=10, pady=(4, 8))
        self._mark_nav()

    def _refresh_nav_images(self):
        """After the display scaling changed: the icons again at the new size."""
        for (screen, view), item in getattr(self, "nav", {}).items():
            shape = VIEW_ICONS[view] if screen == "parts" else dict((s, i) for s, _t, i in SCREENS).get(screen, "team")
            item.set_images(self._nav_images(shape))

    def _mark_nav(self):
        for (screen, view), item in getattr(self, "nav", {}).items():
            item.set_chosen(screen == self.screen and (view is None or view == self.view.get()))

    def _update_counts(self):
        """The numbers beside the views and Workflows."""
        nav = getattr(self, "nav", None)
        if not nav:
            return
        counts = list_view.view_counts(self.rows)
        for view in list_view.VIEWS:
            nav[("parts", view)].set_count(counts[view] if self.rows else "")
        mine = workflow_tasks.count_for_me(workflow_tasks.tasks_from_rows(self.rows + list(self.doc_rows), self.identity))
        nav[("tasks", None)].set_count(mine or "")

    def set_view(self, view):
        """Show the parts list with one of its views."""
        self.view.set(view)
        self.show_screen("parts")
        self._render()
        self._selection_changed()

    # -- screens -----------------------------------------------------------------------------------------------
    def show_screen(self, name):
        """Show the parts list ("parts") or one of the other screens ("tasks", "ecos", "documents", "team")."""
        screen = self.screens.get(name)
        if screen is None:
            screen = self.screens[name] = self._make_screen(name)
        for other, widget in self.screens.items():
            if other != name:
                widget.grid_remove()
        screen.grid(row=0, column=0, sticky="nsew")
        self.screen = name
        if name == "tasks":
            screen.reload()
        elif name == "ecos":
            self._load_ecos()
        elif name in ("team", "documents"):
            screen.reload()
        self._mark_nav()

    def _make_screen(self, name):
        if name == "tasks":
            return tasks_screen.TasksScreen(self.content, self)
        if name == "ecos":
            return eco_screen.EcoScreen(self.content, self._view_eco_object, on_add_to_folder=self.add_to_folder)
        if name == "team":
            return team_screen.TeamScreen(self.content, self)
        if name == "documents":
            return documents_screen.DocumentsScreen(self.content, self)
        raise KeyError(name)

    def _load_ecos(self):
        screen = self.screens.get("ecos")
        if screen is not None and self.repo():
            ecos, problems = eco_store.load_all(self.repo())
            screen.show(project_visibility.shown_ecos(self.repo(), ecos), problems)     # less hidden projects'

    # -- narrow windows ------------------------------------------------------------------------------------------
    def set_sidebar_collapsed(self, collapsed, chosen=False):
        """Show only the sidebar's icons (collapsed) or their names too. `chosen`: the person asked for it, so a
        change of window size won't undo it."""
        if chosen:
            self.sidebar_choice = collapsed
        self.sidebar_collapsed = collapsed
        for item in getattr(self, "nav", {}).values():
            item.set_collapsed(collapsed)
        for heading in (self.parts_heading, self.process_heading):
            if collapsed:
                heading.grid_remove()
            else:
                heading.grid()
        self.collapse_button.configure(text="»" if collapsed else "«")
        self.sidebar.columnconfigure(0, minsize=0 if collapsed else self._px(176))

    def _on_window_resized(self, event):
        if event.widget is not self:
            return
        if getattr(self, "sidebar_choice", None) is not None:
            return
        narrow = ui_scale.sidebar_collapsed(event.width, getattr(self, "scale", 1.0))
        if narrow != self.sidebar_collapsed:
            self.set_sidebar_collapsed(narrow)
