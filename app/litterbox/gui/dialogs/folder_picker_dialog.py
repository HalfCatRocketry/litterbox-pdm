"""
folder_picker_dialog.py - Add to Folder...: choose the folder to put the ticked parts (or documents, or ECOs) in,
among the folders you may change (Personal, Team, your projects'), or make a new one first with New Folder....

    chosen = FolderPickerDialog(parent, places, count).show()
    # None if cancelled, else (Place, folder id, [the changes that make new folders first])
    # places: [(folders.folder_actions.Place, title, tree)]
"""

from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox.folders import folder_actions
from litterbox.folders import folder_model
from litterbox.folders.folder_model import FolderError
from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.dialogs import text_input
from litterbox.gui.widgets import modal_dialog
from litterbox.gui.widgets import release_button


class FolderPickerDialog(modal_dialog.ModalDialog):
    def __init__(self, parent, places, count):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.result = None
        self.places = {f"top{index}": (place, title, dict(tree)) for index, (place, title, tree) in enumerate(places)}
        self.new_ops = {}                       # top iid -> changes making new folders there
        width, height = 480, 560
        self.title("Add to Folder")
        window_chrome.place_over(self, parent, width, height)
        self.minsize(380, 400)
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ctk.CTkLabel(self, text=f"Put the {count} chosen in which folder?" if count != 1 else
                     "Put it in which folder?", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=20, pady=(18, 6))
        frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=10)
        frame.grid(row=1, column=0, sticky="nsew", padx=20)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.tree.bind("<Double-1>", lambda event: self._ok())
        self.problem = ctk.CTkLabel(self, text="" if places else "There are no folders you may change.",
                                    text_color=theme.ERROR, anchor="w")
        self.problem.grid(row=2, column=0, sticky="ew", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 18))
        buttons.columnconfigure((0, 1, 2), weight=1, uniform="c")
        release_button.ReleaseButton(buttons, text="New Folder...", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self._new_folder).grid(
            row=0, column=0, sticky="ew", padx=(0, 6))
        release_button.ReleaseButton(buttons, text="Cancel", height=38, fg_color=theme.GRAY,
                                     hover_color=theme.GRAY_HOVER, command=self.destroy).grid(
            row=0, column=1, sticky="ew", padx=6)
        release_button.ReleaseButton(buttons, text="Add", height=38, fg_color=theme.GREEN,
                                     hover_color=theme.GREEN_HOVER, command=self._ok).grid(
            row=0, column=2, sticky="ew", padx=(6, 0))
        self._fill()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda event: self.destroy())
        self.after(150, self._grab)

    def _fill(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for top, (_place, title, tree) in self.places.items():
            self.tree.insert("", "end", iid=top, text=title, open=True)

            def visit(parent_id, parent_iid):
                for folder in folder_model.children(tree, parent_id):
                    iid = f"{top}|{folder.id}"
                    self.tree.insert(parent_iid, "end", iid=iid, text=folder.name, open=True)
                    visit(folder.id, iid)

            visit("", top)
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.see(select)

    def _chosen(self):
        chosen = self.tree.selection()
        if not chosen:
            return None, ""
        top, _bar, folder = chosen[0].partition("|")
        return top, folder

    def _new_folder(self):
        top, parent = self._chosen()
        if top is None:
            self.problem.configure(text="Click where the new folder goes first.")
            return
        name = text_input.InputDialog(text="Name of the new folder:", title="New Folder").get_input()
        if name is None:
            return
        _place, _title, tree = self.places[top]
        try:
            op = folder_actions.add_folder(tree, parent, name)
        except FolderError as e:
            messagebox.showwarning("New Folder", str(e), parent=self)
            return
        folder_model.apply(tree, op)
        self.new_ops.setdefault(top, []).append(op)
        self._fill(select=f"{top}|{op['folder']}")
        self.problem.configure(text="")

    def _ok(self):
        top, folder = self._chosen()
        if top is None or not folder:
            self.problem.configure(text="Choose a folder (or make one with New Folder...).")
            return
        place, _title, _tree = self.places[top]
        self.result = (place, folder, list(self.new_ops.get(top, [])))
        self.destroy()
