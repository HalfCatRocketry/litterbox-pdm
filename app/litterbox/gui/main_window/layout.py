"""
layout.py - building the main window: header, banner, buttons, the parts list and the log.
"""

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from litterbox import version
from litterbox.gui import theme
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import list_view
from litterbox.gui.logic import org_menu
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting


class WindowLayout:
    """building the main window: header, banner, buttons, the parts list and the log. (a part of the main window, App)."""

    def _button(self, parent, text, command, **options):
        button = release_button.ReleaseButton(parent, text=text, command=command, **options)
        self.buttons.append(button)
        if text in action_rules.BUTTON_ACTIONS:
            self.action_buttons[text] = button
        return button

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # Header and vault folder
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 6))
        header.columnconfigure((0, 2), weight=1)
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_row, text="Litterbox", font=ctk.CTkFont(size=26, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.org_var = tk.StringVar(value=self.org or "No org")
        self.org_menu = ctk.CTkOptionMenu(
            title_row, variable=self.org_var, values=org_menu.org_menu_values(self.settings), width=120,
            height=32, fg_color=theme.GRAY, button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
            command=self.on_org_chosen)
        self.org_menu.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.buttons.append(self.org_menu)
        who_box = ctk.CTkFrame(header, fg_color="transparent")
        who_box.grid(row=0, column=2, rowspan=3, sticky="ne")
        self.identity_label = ctk.CTkLabel(who_box, text="", text_color=theme.MUTED, anchor="e")
        self.identity_label.grid(row=0, column=0, padx=(0, 10))
        self.tasks_button = self._button(who_box, "My Tasks", self.show_tasks, width=100, height=30, fg_color=theme.GRAY,
                                         hover_color=theme.GRAY_HOVER)
        self.tasks_button.grid(row=0, column=1, padx=(0, 6))
        team_button = self._button(who_box, "Team...", self.show_team, width=90, height=30, fg_color=theme.GRAY,
                                   hover_color=theme.GRAY_HOVER)
        team_button.grid(row=0, column=2)
        for button in (team_button, self.tasks_button):
            self.buttons.remove(button)         # opening these windows only reads, so they work while busy
        self.update_button = ctk.CTkButton(
            who_box, text=f"Version {version.display()}  -  check for updates", width=0, height=22, fg_color="transparent",
            hover_color=theme.GRAY_HOVER, text_color=theme.MUTED, font=ctk.CTkFont(size=11), command=self.check_for_updates)
        self.update_button.grid(row=1, column=0, columnspan=3, sticky="e", pady=(4, 0))
        ctk.CTkLabel(header, text="Shared vault check-in / check-out", text_color=theme.MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w")
        self.folder_label = ctk.CTkLabel(header, text=self.repo(), text_color=theme.MUTED, anchor="w")
        self.folder_label.grid(row=2, column=0, sticky="w", pady=(2, 0))

        # The status banner: green Ready / yellow Working / red Error (see job_queue.py). A compact box in the middle
        # of the header, between the title and the person's own buttons.
        self.banner = ctk.CTkFrame(header, corner_radius=10, width=280, height=78, fg_color=theme.GREEN)
        self.banner.grid(row=0, column=1, rowspan=3, padx=24)
        self.banner.grid_propagate(False)
        self.banner.columnconfigure(0, weight=1)
        self.banner_title = ctk.CTkLabel(self.banner, text="Ready", font=ctk.CTkFont(size=24, weight="bold"),
                                         text_color="white", anchor="w")
        self.banner_title.grid(row=0, column=0, padx=(16, 4), pady=(8, 0), sticky="w")
        self.banner_detail = ctk.CTkLabel(self.banner, text="", text_color="white", anchor="nw", justify="left",
                                          wraplength=248, font=ctk.CTkFont(size=11))
        self.banner_detail.grid(row=1, column=0, columnspan=3, padx=16, pady=(0, 6), sticky="nw")
        self.banner_details_button = ctk.CTkButton(self.banner, text="Details...", width=76, height=26,
                                                   fg_color="white", text_color=theme.RED, hover_color="#e8e8e8",
                                                   command=self.show_errors)
        self.banner_dismiss_button = ctk.CTkButton(self.banner, text="Dismiss", width=66, height=26,
                                                   fg_color="transparent", border_width=1, border_color="white",
                                                   text_color="white", hover_color=theme.RED_HOVER,
                                                   command=self.dismiss_errors)

        # Search, filters, refresh
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 8))
        toolbar.columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Search part number, name or description...", height=34)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda event: self._render())
        self.view = ctk.CTkSegmentedButton(toolbar, values=list(list_view.VIEWS), command=lambda value: self._render())
        self.view.set("All")
        self.view.grid(row=0, column=1, padx=(0, 8))
        self.void_box = ctk.CTkCheckBox(toolbar, text="Show void", command=self._render, width=90)
        self.void_box.grid(row=0, column=2, padx=(0, 8))
        self.deselect_button = ctk.CTkButton(toolbar, text="Deselect All", width=96, height=34, fg_color=theme.GRAY,
                                             hover_color=theme.GRAY_HOVER, command=self._deselect_all)
        self.deselect_button.grid(row=0, column=3, padx=(0, 8))
        self._button(toolbar, "Refresh", self.refresh, width=84, height=34,
                     fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER).grid(row=0, column=4, padx=(0, 8))
        self._button(toolbar, "Get Latest", self.get_latest, width=100, height=34,
                     fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER).grid(row=0, column=5)

        # The list of parts
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table_sorting.style_tables()
        self.tree = ttk.Treeview(frame, columns=("tick", "pn", "name", "description", "cots", "rev", "state", "files"),
                                 show="headings", selectmode="browse",
                                 style="Parts.Treeview")
        main_columns = (("pn", "Part number", 140, False),
                        ("name", "Name", 240, True),
                        ("description", "Description", 220, True),
                        ("cots", "COTS", 60, False),
                        ("rev", "Rev", 50, False),
                        ("state", "Status", 230, False),
                        ("files", "Files", 110, False))
        for name, title, width, stretch in main_columns:
            self.tree.column(name, width=width, anchor="w", stretch=stretch)
        self.sorter = table_sorting.TableSorter(self.tree, [(name, title) for name, title, _w, _s in main_columns])
        # The tick boxes: tick parts to act on several at once without worrying about the highlight.
        self.ticked = set()
        self.tree.column("tick", width=40, minwidth=40, anchor="center", stretch=False)
        self.tree.heading("tick", text=list_view.TICK_OFF, anchor="center", command=self._toggle_all_ticks)
        self.tree.bind("<Button-1>", self._on_tree_click, add="+")
        self.tree.bind("<space>", self._tick_highlighted)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons(), add="+")
        for kind, color in theme.ROW_COLORS.items():
            self.tree.tag_configure(kind, foreground=color)
        self.tree.tag_configure("busy", foreground=theme.BANNER_YELLOW)
        self.tree.tag_configure("ticked", background=theme.TICK_BG)       # last, so it wins for the background only
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.tree.bind("<Double-1>", self.show_history)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)

        # Everyday buttons
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 6))
        row1.columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="a")
        big = ctk.CTkFont(size=14, weight="bold")
        for column, (text, command, color, hover) in enumerate((
            ("Check Out", self.check_out, theme.ACCENT, "#18527f"),
            ("Check In", self.check_in, theme.GREEN, theme.GREEN_HOVER),
            ("Save Progress", self.save_progress, theme.TEAL, theme.TEAL_HOVER),
            ("Undo Checkout", self.undo_checkout, theme.RED, theme.RED_HOVER),
            ("Open", self.open_part, theme.TEAL, theme.TEAL_HOVER),
            ("Open Drawing", self.open_drawing, theme.TEAL, theme.TEAL_HOVER),
        )):
            self._button(row1, text, command, height=42, font=big, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 6, 0 if column == 5 else 6))

        # Making parts
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 6))
        row2.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("New Part", self.new_part, theme.ACCENT, "#18527f"),
            ("Import...", self.import_cad, theme.TEAL, theme.TEAL_HOVER),
            ("Import COTS...", self.import_cots, theme.TEAL, theme.TEAL_HOVER),
            ("Edit Details", self.edit_details, theme.ACCENT, "#18527f"),
            ("References...", self.show_references, theme.TEAL, theme.TEAL_HOVER),
        )):
            self._button(row2, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 4 else 4))

        # A part's life: release, revise, and the less common changes
        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 8))
        row3.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1, uniform="b")
        for column, (text, command, color, hover) in enumerate((
            ("Release", self.release, theme.PURPLE, theme.PURPLE_HOVER),
            ("Revise", self.revise, theme.PURPLE, theme.PURPLE_HOVER),
            ("Cancel Revision", self.cancel_revision, theme.GRAY, theme.GRAY_HOVER),
            ("Make COTS", self.make_cots, theme.TEAL, theme.TEAL_HOVER),
            ("Unrelease", self.reopen, theme.GRAY, theme.GRAY_HOVER),
            ("Void", self.void, theme.GRAY, theme.GRAY_HOVER),
            ("History", self.show_history, theme.GRAY, theme.GRAY_HOVER),
        )):
            self._button(row3, text, command, height=34, fg_color=color,
                         hover_color=hover).grid(row=0, column=column, sticky="ew",
                                                 padx=(0 if column == 0 else 4, 0 if column == 6 else 4))

        # Status line and log
        self.status = ctk.CTkLabel(self, text="Ready", text_color=theme.MUTED, anchor="w")
        self.status.grid(row=6, column=0, sticky="ew", padx=26)
        self.log_box = ctk.CTkTextbox(self, height=110, fg_color=theme.BG_PANEL, text_color=theme.MUTED,
                                      font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.grid(row=7, column=0, sticky="ew", padx=24, pady=(4, 20))
        self.log_box.configure(state="disabled")
