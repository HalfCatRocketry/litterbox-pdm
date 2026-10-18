"""
references_window.py - what a part uses and where it is used, with Update references.
"""

from tkinter import messagebox, ttk

import customtkinter as ctk

from litterbox.gui import theme
from litterbox.gui import window_chrome
from litterbox.gui.logic import list_view
from litterbox.gui.logic import reference_text
from litterbox.gui.widgets import release_button
from litterbox.gui.widgets import table_sorting
from litterbox.references import reference_replace


class ReferencesWindow(ctk.CTkToplevel):
    """What a part uses and where it is used. Click a box to select, then replace the chosen
    references with the latest released revision. Only assemblies that are still in work can change.

    The window stays open while references are being updated: set_busy() greys it out with a message,
    and show() fills it in again with the new data."""

    def __init__(self, parent, pn, name, uses_list, used_list, on_replace, this_outdated=False, others_outdated=(),
                 on_update=None):
        super().__init__(parent)
        window_chrome.set_window_icon(self)
        self.pn = pn
        self.title(f"References - {pn.short}")
        self.geometry("980x640")
        self.minsize(720, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.on_replace = on_replace
        self.on_update = on_update                 # on_update(window, [PN, ...])
        self.busy = False
        self.title_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=18, weight="bold"), anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w", padx=20, pady=(16, 4))
        self.body = None
        self.show(name, uses_list, used_list, this_outdated, others_outdated)
        self.after(100, self.lift)

    def show(self, name, uses_list, used_list, this_outdated=False, others_outdated=()):
        """(Re)build everything that depends on the data."""
        if self.body is not None:
            self.body.destroy()
        self.busy = False
        pn = self.pn
        self.title_label.configure(text=f"{pn.short}   {name}")
        self.entries = {}                      # (tree, iid) -> Use
        self.trees = []
        self.action_buttons = []
        body = self.body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)
        for row, title, columns, rows, items in (
                (0, "This part uses", (("tick", "", 34), ("pn", "Part", 110), ("name", "Name", 230),
                                       ("rev", "Rev used", 70), ("latest", "Latest released", 100),
                                       ("state", "State", 250)),
                 reference_text.uses_table(uses_list), uses_list),
                (2, "This part is used in", (("tick", "", 34), ("pn", "Assembly", 110), ("name", "Name", 200),
                                             ("rev", "Its rev", 60), ("status", "Its status", 80),
                                             ("used", "Rev of this part", 110), ("state", "State", 230)),
                 reference_text.used_in_table(used_list), used_list)):
            ctk.CTkLabel(body, text=title if rows else title + " - nothing", text_color=theme.MUTED, anchor="w").grid(
                row=row, column=0, sticky="w", padx=20, pady=(8, 0))
            frame = ctk.CTkFrame(body, fg_color=theme.BG_PANEL, corner_radius=10)
            frame.grid(row=row + 1, column=0, sticky="nsew", padx=20, pady=(4, 0))
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=6)
            for name_, _title, width in columns:
                tree.column(name_, width=width, anchor="w")
            table_sorting.TableSorter(tree, [(c[0], c[1]) for c in columns])
            tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
            scroll = ctk.CTkScrollbar(frame, command=tree.yview)
            scroll.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 4))
            tree.configure(yscrollcommand=scroll.set)
            for (iid, values, _can), use in zip(rows, items):
                tree.insert("", "end", iid=iid, values=values)
                self.entries[(str(tree), iid)] = use
            tree.bind("<Button-1>", lambda event, tree=tree: self._click(tree, event))
            self.trees.append(tree)

        self.banner_text = None
        stale_note = reference_text.outdated_note(pn, this_outdated, others_outdated)
        if stale_note:
            banner = ctk.CTkFrame(body, fg_color=theme.BG_PANEL, corner_radius=10)
            banner.grid(row=4, column=0, sticky="ew", padx=20, pady=(10, 0))
            self.banner_text = ctk.CTkLabel(banner, text=stale_note, text_color="#e5c07b", anchor="w",
                                            justify="left", wraplength=560)
            self.banner_text.grid(row=0, column=0, sticky="w", padx=12, pady=8)
            self.banner_note = stale_note
            actions = ctk.CTkFrame(banner, fg_color="transparent")
            actions.grid(row=0, column=1, padx=8, pady=6)
            if this_outdated:
                self.action_buttons.append(release_button.ReleaseButton(
                    actions, text="Update this part", width=150, fg_color=theme.ACCENT, hover_color="#18527f",
                    command=lambda: self._update([pn])))
                self.action_buttons[-1].grid(row=0, column=0, padx=4)
            if others_outdated:
                self.action_buttons.append(release_button.ReleaseButton(
                    actions, text=f"Update all ({len(others_outdated) + int(this_outdated)})", width=130,
                    fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                    command=lambda: self._update(([pn] if this_outdated else []) + list(others_outdated))))
                self.action_buttons[-1].grid(row=0, column=1, padx=4)
            banner.columnconfigure(0, weight=1)

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=5, column=0, sticky="ew", padx=20, pady=14)
        for column, (text, width, color, hover, command) in enumerate((
                ("Select all that can change", 190, theme.GRAY, theme.GRAY_HOVER, self._tick_all),
                ("Replace selected with latest released", 250, theme.PURPLE, theme.PURPLE_HOVER, self._replace))):
            button = release_button.ReleaseButton(buttons, text=text, width=width, fg_color=color, hover_color=hover,
                                   command=command)
            button.grid(row=0, column=column, padx=(0, 8))
            self.action_buttons.append(button)
        release_button.ReleaseButton(buttons, text="Close", width=100, fg_color=theme.GRAY, hover_color=theme.GRAY_HOVER,
                      command=self.destroy).grid(row=0, column=2)
        ctk.CTkLabel(buttons, text="Released assemblies are frozen: revise the assembly to change them.",
                     text_color=theme.MUTED).grid(row=0, column=3, padx=14)
        self._tick_all()

    def set_busy(self, message):
        """Grey out the buttons and show what is happening, without closing the window."""
        self.busy = True
        for button in self.action_buttons:
            button.configure(state="disabled")
        if self.banner_text is not None:
            self.banner_text.configure(text=message)

    def set_idle(self):
        """Back to normal after a failed update."""
        self.busy = False
        for button in self.action_buttons:
            button.configure(state="normal")
        if self.banner_text is not None:
            self.banner_text.configure(text=self.banner_note)

    def _update(self, pns):
        if self.busy or not self.on_update:
            return
        self.set_busy("Updating references... SolidWorks may start if it is not open.")
        self.on_update(self, pns)

    def _click(self, tree, event):
        if self.busy:
            return
        if tree.identify_column(event.x) != "#1" or tree.identify_region(event.x, event.y) != "cell":
            return
        iid = tree.identify_row(event.y)
        if iid:
            anchor = self.last_click.get(str(tree))
            if list_view.shift_held(event) and anchor is not None and tree.exists(anchor) and tree.set(anchor, "tick"):
                mark = tree.set(anchor, "tick")             # Shift: everything from the last click to here
                for between in list_view.range_between(list(tree.get_children()), anchor, iid):
                    if tree.set(between, "tick"):
                        self._set_mark(tree, between, mark)
            else:
                self._set_mark(tree, iid, reference_text.toggled(tree.set(iid, "tick")))
            self.last_click[str(tree)] = iid

    @staticmethod
    def _set_mark(tree, iid, mark):
        tree.set(iid, "tick", mark)

    def _tick_all(self):
        for tree in self.trees:
            for iid in tree.get_children():
                if tree.set(iid, "tick"):
                    self._set_mark(tree, iid, reference_text.CHECKED)

    def _replace(self):
        if self.busy:
            return
        chosen, seen = [], set()
        for tree in self.trees:
            for iid in tree.get_children():
                use = self.entries.get((str(tree), iid))
                if use is not None and tree.set(iid, "tick") == reference_text.CHECKED and use.replaceable:
                    key = (use.parent, use.child, use.child_revision)
                    if key not in seen:
                        seen.add(key)
                        chosen.append(reference_replace.Replacement(use.parent, use.child, use.child_revision))
        if not chosen:
            messagebox.showinfo("Nothing selected", "Select at least one reference to replace.")
            return
        self.destroy()
        self.on_replace(chosen)
