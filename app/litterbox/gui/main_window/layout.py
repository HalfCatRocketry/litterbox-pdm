"""
layout.py - building the main window: the menu bar, the header (org, who you are, My Tasks, Get Latest), the
sidebar, the parts screen (toolbar, search, list) beside the details pane, the log drawer and the status bar.
Each area's behaviour lives in its own file (menus.py, sidebar.py, parts_list.py, detail_pane.py, status_bar.py).

    +-----------------------------------------------------------------------+
    | File  Vault  View  Help                               [logo] Litterbox |
    | [HCR v]  C:\\Litterbox\\hcr-litterbox      Austin (Admin)  My Tasks  Get Latest |
    | sidebar |  toolbar / search / parts list           |  details pane     |
    | (log drawer, when open)                                                |
    | * Ready  .  what just happened                     SolidWorks  Jobs  Log |
    +-----------------------------------------------------------------------+
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import org_menu
from litterbox.gui.panes import part_details
from litterbox.gui.widgets import menu_bar
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import tooltip


# The four everyday buttons along the top of the list. Everything else is in the menus beside them.
EVERYDAY = (("Check Out", "check_out", theme.ACCENT, "#18527f"),
            ("Check In", "check_in", theme.GREEN, theme.GREEN_HOVER),
            ("Save Progress", "save_progress", theme.TEAL, theme.TEAL_HOVER),
            ("Undo Checkout", "undo_checkout", theme.RED, theme.RED_HOVER))


class WindowLayout:
    """building the main window (a part of the main window, App)."""

    def _build_ui(self):
        self.configure(fg_color=theme.BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        scaling.style_tables(scaling.scale_of(self))
        self.menu_bar = menu_bar.MenuBar(self, self._menus(), logo=self.icons.logo(self._px(18)))
        self.menu_bar.grid(row=0, column=0, sticky="ew")
        self._build_header()
        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_sidebar(body)
        self.content = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self._build_parts_screen(self.content)
        self._build_status_bar()
        self.bind("<Configure>", self._on_window_resized, add="+")

    def _px(self, size):
        """A size at 100%, in pixels for the plain Tk parts (see gui/scaling.py)."""
        return max(1, round(size * getattr(self, "scale", 1.0)))

    # -- header ------------------------------------------------------------------------------------------------
    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 6))
        header.columnconfigure(2, weight=1)
        self.org_var = tk.StringVar(value=self.org or "No org")
        self.org_menu = ctk.CTkOptionMenu(
            header, variable=self.org_var, values=org_menu.org_choices(self.settings), width=110, height=30,
            fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
            font=ctk.CTkFont(size=14, weight="bold"), command=self.on_org_chosen)
        self.org_menu.grid(row=0, column=0, sticky="w")
        tooltip.Tooltip(self.org_menu, self._org_tooltip)
        self.folder_label = ctk.CTkLabel(header, text=self.repo(), text_color=theme.MUTED, anchor="w")
        self.folder_label.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.identity_label = ctk.CTkLabel(header, text="", text_color=theme.MUTED, anchor="e")
        self.identity_label.grid(row=0, column=3, sticky="e", padx=(0, 10))
        self.tasks_button = release_button.ReleaseButton(header, text="My Tasks", width=100, height=30,
                                                         fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                                         command=lambda: self.show_screen("tasks"))
        self.tasks_button.grid(row=0, column=4, padx=(0, 6))
        self.get_latest_button = release_button.ReleaseButton(header, text="Get Latest", width=100, height=30,
                                                              fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                                              command=self.get_latest)
        self.get_latest_button.grid(row=0, column=5)
        tooltip.Tooltip(self.get_latest_button, "Download what others have uploaded since you last looked.")

    def _org_tooltip(self):
        name = self._org_name()
        return f"{name}\n{self.repo()}" if name and name != self.org else self.repo()

    # -- the parts screen ------------------------------------------------------------------------------------------
    def _build_parts_screen(self, parent):
        self.parts_screen = ttk.PanedWindow(parent, orient="horizontal")
        self.parts_screen.grid(row=0, column=0, sticky="nsew")
        center = ctk.CTkFrame(self.parts_screen, fg_color=theme.BG, corner_radius=0)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(2, weight=1)
        self.parts_screen.add(center, weight=1)
        self._build_toolbar(center)
        self._build_search_row(center)
        self._build_list(center)
        self.detail_frame = ctk.CTkFrame(self.parts_screen, fg_color=theme.BG, corner_radius=0, width=330)
        self._build_detail_pane(self.detail_frame)
        if self.settings.get("details_pane", True) is not False:
            self.parts_screen.add(self.detail_frame, weight=0)
        self.screens = {"parts": self.parts_screen}

    def _build_toolbar(self, parent):
        self.toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=(2, 6))
        self.everyday = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self.everyday.grid(row=0, column=0, sticky="w")
        big = ctk.CTkFont(size=14, weight="bold")
        for column, (text, method, color, hover) in enumerate(EVERYDAY):
            button = release_button.ReleaseButton(self.everyday, text=text, command=getattr(self, method), height=36,
                                                  width=100, font=big, fg_color=color, hover_color=hover)
            button.grid(row=0, column=column, padx=(0, 6))
            self.action_buttons[text] = button
            tooltip.Tooltip(button, lambda text=text: self._why_greyed(text))
        self.more = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self.more.grid(row=0, column=1, sticky="w", padx=(4, 0))
        for column, (title, fill) in enumerate(self._toolbar_menus()):
            menu_bar.DropButton(self.more, title, fill, height=36, width=84, fg_color=theme.GRAY,
                                hover_color=theme.GRAY_HOVER).grid(row=0, column=column, padx=(0, 6))
        self.toolbar.bind("<Configure>", lambda event: self._arrange_toolbar(event.width), add="+")

    def _arrange_toolbar(self, width):
        """On a narrow window the menus move under the everyday buttons instead of running off the edge."""
        try:
            needed = self.everyday.winfo_reqwidth() + self.more.winfo_reqwidth() + self._px(8)
        except Exception:
            return
        if width < needed:
            self.more.grid_configure(row=1, column=0, padx=(0, 0), pady=(6, 0))
        else:
            self.more.grid_configure(row=0, column=1, padx=(4, 0), pady=(0, 0))

    def _build_search_row(self, parent):
        self.search_row = outer = ctk.CTkFrame(parent, fg_color="transparent")
        outer.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(0, 6))
        outer.columnconfigure(0, weight=1)
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1, minsize=self._px(150))
        self.search = ctk.CTkEntry(row, placeholder_text="Search  (* and ? are wildcards)", height=32)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.search.bind("<KeyRelease>", lambda event: self._render())
        tooltip.Tooltip(self.search, "Plain text finds it anywhere: bracket finds Motor Bracket.\n"
                                     "* stands for any characters and ? for one, and then the whole value must "
                                     "match: Te*rt finds Test Part but not My Test Part. Capitals never matter.")
        self.search_in = tk.StringVar(value=list_columns.ALL_COLUMNS)
        self.search_in_menu = ctk.CTkOptionMenu(row, variable=self.search_in, height=32, width=140,
                                                values=list_columns.search_choices(self.list_keys),
                                                fg_color=theme.GRAY, button_color=theme.GRAY_HOVER,
                                                button_hover_color=theme.ACCENT, command=lambda value: self._render())
        self.search_in_menu.grid(row=0, column=1, padx=(0, 6))
        tooltip.Tooltip(self.search_in_menu, "Which column the search looks in.")
        menu_bar.DropButton(row, "Columns", self._fill_columns_menu, height=32, width=96, fg_color=theme.GRAY,
                            hover_color=theme.GRAY_HOVER).grid(row=0, column=2)
        self.ticks_box = ctk.CTkFrame(outer, fg_color="transparent")
        self.ticks_box.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.acting_label = ctk.CTkLabel(self.ticks_box, text="", text_color=theme.MUTED, anchor="e")
        self.acting_label.grid(row=0, column=0, padx=(0, 6))
        tooltip.Tooltip(self.acting_label, "Check Out, Check In, Release and the other changes act on the parts "
                                           "whose boxes are ticked. Clicking a row only shows its details.")
        self.deselect_button = ctk.CTkButton(self.ticks_box, text="Clear", width=60, height=32, fg_color=theme.GRAY,
                                             hover_color=theme.GRAY_HOVER, command=self._deselect_all)
        self.deselect_button.grid(row=0, column=1)
        tooltip.Tooltip(self.deselect_button, "Untick every box.")
        outer.bind("<Configure>", lambda event: self._arrange_search_row(event.width), add="+")

    def _arrange_search_row(self, width):
        """On a narrow window the ticks note and Clear move under the search box, which keeps its room."""
        try:
            needed = self._px(150) + self.search_in_menu.winfo_reqwidth() + self._px(110) + \
                self.ticks_box.winfo_reqwidth() + self._px(20)
        except Exception:
            return
        if width < needed:
            self.ticks_box.grid_configure(row=1, column=0, sticky="w", padx=(0, 0), pady=(6, 0))
        else:
            self.ticks_box.grid_configure(row=0, column=1, sticky="e", padx=(10, 0), pady=(0, 0))

    def _build_list(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=theme.BG_PANEL, corner_radius=8)
        frame.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[c.key for c in list_columns.COLUMNS], show="tree headings",
                                 selectmode="browse", style="Parts.Treeview")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=(6, 0))
        self.sorter = None
        self._set_up_columns()
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<Button-3>", self._on_right_click, add="+")
        self.tree.bind("<space>", self._tick_highlighted)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._selection_changed(), add="+")
        self.tree.bind("<Double-1>", self.show_history)
        self.tree.bind("<Configure>", lambda event: self._refit_soon(), add="+")
        self.tree.bind("<ButtonRelease-1>", lambda event: self._refit_soon(), add="+")    # after a column resize
        for kind, color in theme.ROW_COLORS.items():
            self.tree.tag_configure(kind, foreground=color)
        self.tree.tag_configure("busy", foreground=theme.BANNER_YELLOW)
        self.tree.tag_configure("ticked", background=theme.TICK_BG)       # last, so it wins for the background only
        tooltip.TableTooltip(self.tree, self._cell_tooltip)
        down = ctk.CTkScrollbar(frame, command=self.tree.yview)
        down.grid(row=0, column=1, sticky="ns", pady=(6, 0), padx=(0, 2))
        across = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.tree.xview)
        across.grid(row=1, column=0, sticky="ew", padx=(6, 0), pady=(0, 2))
        self.tree.configure(yscrollcommand=down.set, xscrollcommand=across.set)

    # -- the details pane --------------------------------------------------------------------------------------
    def _build_detail_pane(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=(6, 10), pady=(2, 0))
        top.columnconfigure(1, weight=1)
        self.pane_icon = tk.Label(top, bg=theme.BG, bd=0)
        self.pane_icon.grid(row=0, column=0, padx=(0, 8))
        self.pane_title = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=16, weight="bold"), anchor="w",
                                       justify="left", wraplength=220)
        self.pane_title.grid(row=0, column=1, sticky="ew")
        pop = ctk.CTkButton(top, text="\u29c9", width=32, height=28, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                            command=self.show_history)
        pop.grid(row=0, column=2, padx=(6, 4))
        tooltip.Tooltip(pop, "Open these details in a window of their own.")
        hide = ctk.CTkButton(top, text="\u00bb", width=32, height=28, fg_color=theme.GRAY,
                             hover_color=theme.GRAY_HOVER, command=lambda: self.set_details_pane(False))
        hide.grid(row=0, column=3)
        tooltip.Tooltip(hide, "Hide the details pane (View > Details pane brings it back).")
        self.pane_state = ctk.CTkLabel(parent, text="Click a part to see its details.", text_color=theme.MUTED,
                                       anchor="w", justify="left", wraplength=320)
        self.pane_state.grid(row=1, column=0, sticky="ew", padx=(6, 10), pady=(0, 4))
        self.pane_view = part_details.PartDetailsView(
            parent, on_open=self._pane_open, on_view_eco=self.view_eco, references=True,
            on_tab=lambda name: self._pane_tab_changed(name), on_manage_references=self.show_references)
        self.pane_view.grid(row=2, column=0, sticky="nsew", padx=(6, 10), pady=(0, 6))
        parent.bind("<Configure>", lambda event: self._wrap_pane(event.width), add="+")

    def _wrap_pane(self, width):
        """Long text in the pane's header wraps to the pane's width (labels want sizes at 100%)."""
        logical = width / getattr(self, "scale", 1.0)
        self.pane_state.configure(wraplength=max(logical - 30, 120))
        self.pane_title.configure(wraplength=max(logical - 130, 100))
