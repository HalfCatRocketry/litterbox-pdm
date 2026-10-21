"""
doc_types_dialog.py - Team > Document Types... (Admins and the Owner): the org's document types, each with a name
and the prefix its numbers take. Add one, change a name or prefix, hide one nobody should use any more, or remove
one no document uses (documents/doc_types.py).
"""

from tkinter import ttk

import customtkinter as ctk

from litterbox.documents import doc_types
from litterbox.gui import scaling
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class DocTypesDialog(modal_dialog.ModalDialog):
    """DocTypesDialog(parent, types, used).show() -> None if cancelled or unchanged, else the new list of DocTypes.
    `used` is {type key: how many documents} (doc_types.in_use)."""

    def __init__(self, parent, types, used):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result, self.used = None, dict(used)
        self.types = [doc_types.DocType(t.key, t.name, t.prefix, t.hidden, dict(t.extra)) for t in types]
        self.before = [t.to_dict() | {"key": t.key} for t in self.types]
        width, height = 640, 520
        x = parent.winfo_rootx() + max((parent.winfo_width() - width) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - height) // 4, 0)
        self.title("Document Types")
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(520, 420)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text="Document types and their number prefixes (Propulsion Document, PROP: PROP-0001)",
                     anchor="w", wraplength=600, justify="left").grid(row=0, column=0, sticky="ew", padx=20,
                                                                      pady=(18, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        scale = scaling.scale_of(self)
        self.tree = ttk.Treeview(frame, columns=("name", "prefix", "shown", "used"), show="headings", selectmode="browse")
        for name, title, size in (("name", "Name", 230), ("prefix", "Prefix", 80), ("shown", "Offered", 80),
                                  ("used", "Documents", 90)):
            self.tree.heading(name, text=title, anchor="w")
            self.tree.column(name, width=int(size * scale), anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._picked())

        edit = ctk.CTkFrame(self, fg_color="transparent")
        edit.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 0))
        edit.columnconfigure(1, weight=1)
        ctk.CTkLabel(edit, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.name_entry = ctk.CTkEntry(edit, height=32)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        ctk.CTkLabel(edit, text="Prefix").grid(row=0, column=2, sticky="w", padx=(0, 8))
        self.prefix_entry = ctk.CTkEntry(edit, width=90, height=32)
        self.prefix_entry.grid(row=0, column=3)
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="w", padx=20, pady=(8, 0))
        for column, (text, command) in enumerate((("Add", self._add), ("Change", self._change),
                                                  ("Hide / Offer", self._toggle), ("Remove", self._remove))):
            release_button.ReleaseButton(actions, text=text, width=110, height=30, fg_color=theme.GRAY,
                                         hover_color=theme.GRAY_HOVER, command=command).grid(row=0, column=column,
                                                                                             padx=(0, 6))
        self.problem = ctk.CTkLabel(self, text="", text_color=theme.ERROR, anchor="w", justify="left", wraplength=600)
        self.problem.grid(row=4, column=0, sticky="ew", padx=20, pady=(6, 0))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                                     command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Save for everyone", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._save).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _fill(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for t in self.types:
            self.tree.insert("", "end", iid=t.key, values=(t.name, t.prefix, "No" if t.hidden else "Yes",
                                                           self.used.get(t.key, 0)))
        if select and self.tree.exists(select):
            self.tree.selection_set(select)

    def _selected(self):
        chosen = self.tree.selection()
        return next((t for t in self.types if chosen and t.key == chosen[0]), None)

    def _picked(self):
        chosen = self._selected()
        if chosen is not None:
            for entry, text in ((self.name_entry, chosen.name), (self.prefix_entry, chosen.prefix)):
                entry.delete(0, "end")
                entry.insert(0, text)

    def _check(self, types):
        try:
            doc_types.validate([doc_types.DocType(t.key, t.name, t.prefix, t.hidden) for t in types])
        except doc_types.DocTypeError as e:
            self.problem.configure(text=str(e))
            return False
        self.problem.configure(text="")
        return True

    def _add(self):
        new = doc_types.DocType(doc_types.make_key(self.name_entry.get(), {t.key for t in self.types}),
                                self.name_entry.get(), self.prefix_entry.get())
        if self._check(self.types + [new]):
            doc_types.validate([new])
            self.types.append(new)
            self._fill(new.key)

    def _change(self):
        chosen = self._selected()
        if chosen is None:
            self.problem.configure(text="Click a type first.")
            return
        trial = [doc_types.DocType(t.key, self.name_entry.get(), self.prefix_entry.get(), t.hidden)
                 if t is chosen else t for t in self.types]
        if self._check(trial):
            chosen.name, chosen.prefix = self.name_entry.get(), self.prefix_entry.get()
            doc_types.validate([chosen])
            self._fill(chosen.key)

    def _toggle(self):
        chosen = self._selected()
        if chosen is not None:
            chosen.hidden = not chosen.hidden
            self._fill(chosen.key)

    def _remove(self):
        chosen = self._selected()
        if chosen is None:
            return
        if self.used.get(chosen.key):
            self.problem.configure(text=f"{chosen.name} is used by documents, so it can't be removed. Hide it instead.")
            return
        self.types.remove(chosen)
        self._fill()

    def _save(self):
        if not self._check(self.types):
            return
        after = [t.to_dict() | {"key": t.key} for t in self.types]
        self.result = self.types if after != self.before else None
        self.destroy()
