"""
templates_dialog.py - Team > Templates...: the SolidWorks templates new parts, assemblies and drawings are made from
(core/template_rules.py), the org's and each project's. Everyone may look; whoever may change the shown owner's
(vault/template_access.py) adds, removes and chooses the default. show() gives the button pressed: ("add", project,
file path), ("remove", key), ("default", key) (core/template_rules.Template.key), or None for Close. The main window does the work, then opens this
again (gui/main_window/team_admin.py).

    TemplatesDialog(parent, templates, owners, may_change, project="").show()
    # owners: the projects to offer besides the org; may_change(project) -> (True, "") or (False, why)
"""

from tkinter import filedialog, ttk

import customtkinter as ctk

from litterbox.core import file_types
from litterbox.core import template_rules
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import template_text
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class TemplatesDialog(modal_dialog.ModalDialog):
    def __init__(self, parent, templates, owners, may_change, project=template_rules.ORG):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.templates, self.may_change = None, list(templates), may_change
        self.titles = {template_text.owner_title(template_rules.ORG): template_rules.ORG}
        self.titles.update({template_text.owner_title(name): name for name in owners})
        width, height = 720, 520
        self.title("Templates")
        window_chrome.place_over(self, parent, width, height, down=4)
        window_chrome.min_size(self, 560, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="SolidWorks templates", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        ctk.CTkLabel(self, text=template_text.HOW_IT_WORKS, text_color=theme.MUTED, anchor="w", justify="left",
                     wraplength=width - 50).grid(row=1, column=0, sticky="ew", padx=20)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 6))
        ctk.CTkLabel(top, text="Templates of").grid(row=0, column=0, padx=(0, 8))
        self.owner = ctk.CTkOptionMenu(top, values=list(self.titles), width=240, height=32, fg_color=theme.GRAY,
                                       button_color=theme.GRAY_HOVER, button_hover_color=theme.ACCENT,
                                       command=lambda _value: self._fill())
        self.owner.set(template_text.owner_title(project if project in self.titles.values() else template_rules.ORG))
        self.owner.grid(row=0, column=1)
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=3, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("name", "kind", "default"), show="headings", selectmode="browse")
        for name, title, size in (("name", "Name", 330), ("kind", "Kind", 120), ("default", "Default", 100)):
            self.tree.heading(name, text=title, anchor="w")
            self.tree.column(name, width=size, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scroll = ctk.CTkScrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
        self.tree.configure(yscrollcommand=scroll.set)
        self.note = ctk.CTkLabel(self, text="", text_color=theme.MUTED, anchor="w", justify="left",
                                 wraplength=width - 50)
        self.note.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(8, 16))
        self.buttons = {}
        for column, (text, action) in enumerate((("Add...", "add"), ("Make Default", "default"),
                                                 ("Remove...", "remove"))):
            self.buttons[action] = release_button.ReleaseButton(
                buttons, text=text, height=34, width=110, fg_color=theme.ACCENT, command=lambda a=action: self._choose(a))
            self.buttons[action].grid(row=0, column=column, sticky="w", padx=(0, 8))
        release_button.ReleaseButton(buttons, text="Close", height=34, width=80, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(row=0, column=3, sticky="e")
        buttons.columnconfigure(3, weight=1)
        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _project(self):
        return self.titles.get(self.owner.get(), template_rules.ORG)

    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        rows = template_text.rows(self.templates, self._project())
        for key, name, kind, default in rows:
            self.tree.insert("", "end", iid=key, values=(name, kind, default))
        allowed, why = self.may_change(self._project())
        for button in self.buttons.values():
            button.configure(state="normal" if allowed else "disabled")
        if not allowed:
            self.note.configure(text=why, text_color=theme.WARN)
        elif not rows:
            self.note.configure(text="None yet. Add... copies a template file (.prtdot, .asmdot or .drwdot) into the "
                                     "vault. The first of each kind is the default.", text_color=theme.MUTED)
        else:
            self.note.configure(text="Select a template to make it the default of its kind, or to remove it.",
                                text_color=theme.MUTED)

    def _choose(self, action):
        if action == "add":
            kinds = [(f"{template_rules.LABELS[kind]} templates", "*" + ext)
                     for kind, ext in file_types.TEMPLATES["SolidWorks"].items()]
            path = filedialog.askopenfilename(
                parent=self, title="A SolidWorks template to add",
                filetypes=[("SolidWorks templates", " ".join(f"*{e}" for e in file_types.TEMPLATE_EXTENSIONS))] + kinds)
            if not path:
                return
            self.result = ("add", self._project(), path)
        else:
            chosen = self.tree.selection()
            if not chosen:
                self.note.configure(text="Select a template in the list first.", text_color=theme.WARN)
                return
            self.result = (action, chosen[0])
        self.destroy()
