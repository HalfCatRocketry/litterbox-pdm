"""
menus.py - the window's menus: File, Vault, View and Help in the menu bar, the Part / Lifecycle / Create menus
beside the everyday buttons, and the right-click menu on a part. An entry that can't be used right now is greyed out
(the status line says why when the mouse is on it).
"""

import tkinter as tk
from tkinter import messagebox

from litterbox import version
from litterbox.core.part_number import parse as parse_pn
from litterbox.gui.dialogs import legend_dialog
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import org_menu
from litterbox.gui.logic import ui_scale
from litterbox.gui.widgets import menu_bar

# The menus beside the everyday buttons: (label, App method). The labels are action_rules.BUTTON_ACTIONS keys where
# the entry depends on the ticked or highlighted parts. None is a line between entries.
PART_MENU = (("Open", "open_part"), ("Open Drawing", "open_drawing"), None,
             ("References...", "show_references"), ("Details", "show_history"), None,
             ("Generate STEP/PDF", "generate_step_pdf"), ("Export Files", "export_files"))


LIFECYCLE_MENU = (("Edit Details", "edit_details"), ("Purchasing Info", "edit_purchasing"), None, ("Release", "release"), ("Revise", "revise"),
                  ("Cancel Revision", "cancel_revision"), None, ("Make COTS", "make_cots"),
                  ("Unrelease", "reopen"), ("Void", "void"))


CREATE_MENU = (("New Part", "new_part"), ("New Assembly", "new_assembly"), ("Import...", "import_cad"),
               ("Import COTS...", "import_cots"))


EVERYDAY_MENU = (("Check Out", "check_out"), ("Check In", "check_in"), ("Save Progress", "save_progress"),
                 ("Undo Checkout", "undo_checkout"))


ADMIN_LIFECYCLE_MENU = (None, ("Break Checkout", "break_checkout"))      # only for those who may (Admin, Owner)


# Where an entry reads differently from its button
ENTRY_TEXT = {"Details": "Details and History...", "Break Checkout": "Break Checkout...",
              "Purchasing Info": "Purchasing Info...", "Export Files": "Export Files...",
              "Generate STEP/PDF": "Generate STEP/PDF..."}


class Menus:
    """the window's menus (a part of the main window, App)."""

    def _menu_flag(self, value):
        """A tick for a menu entry. Kept here, because Tk forgets a menu's tick when nothing in Python holds it."""
        flag = tk.BooleanVar(master=self, value=value)
        self.__dict__.setdefault("_menu_flags", []).append(flag)
        del self._menu_flags[:-60]
        return flag

    def _menus(self):
        return [("File", self._fill_file_menu), ("Vault", self._fill_vault_menu), ("View", self._fill_view_menu),
                ("Help", self._fill_help_menu)]

    def _toolbar_menus(self):
        return [("Part", lambda menu: self._fill_actions(menu, PART_MENU)),
                ("Lifecycle", lambda menu: self._fill_actions(menu, self._lifecycle_entries())),
                ("Create", lambda menu: self._fill_actions(menu, CREATE_MENU))]

    def _lifecycle_entries(self):
        """The Lifecycle menu, with Break Checkout for an Admin or the Owner."""
        return LIFECYCLE_MENU + (ADMIN_LIFECYCLE_MENU if self.identity.allows("break_checkout")[0] else ())

    def _fill_actions(self, menu, entries):
        """Add part actions to a menu, greyed out when the ticked or highlighted parts don't allow them."""
        states = action_rules.button_states(self._ticked_pns(), [parse_pn(i) for i in self.tree.selection()],
                                            self.rows_by_pn, self.jobs.pending_parts())
        end = menu.index("end")
        offset = 0 if end is None else end + 1               # entries already in the menu
        reasons = []
        for entry in entries:
            if entry is None:
                menu.add_separator()
                reasons.append("")
                continue
            label, method = entry
            usable = states.get(label, True)
            menu.add_command(label=ENTRY_TEXT.get(label, label), command=getattr(self, method),
                             state="normal" if usable else "disabled")
            reasons.append("" if usable else self._why_greyed(label))
        menu.bind("<<MenuSelect>>", lambda event: self._say_why(menu, reasons, offset), add="+")

    def _say_why(self, menu, reasons, offset=0):
        """While the mouse is on a greyed-out entry, the status line says why."""
        try:
            index = menu.index("active")
        except tk.TclError:
            return
        if index is not None and 0 <= index - offset < len(reasons) and reasons[index - offset]:
            self._say(reasons[index - offset], "warn")

    # -- the menu bar ---------------------------------------------------------------------------------------------
    def _fill_file_menu(self, menu):
        busy = self.busy
        orgs = org_menu.known_orgs(self.settings)
        for org in orgs:
            menu.add_radiobutton(label=org, value=org, variable=self._org_flag(),
                                 command=lambda org=org: self.on_org_chosen(org),
                                 state="disabled" if busy else "normal")
        if orgs:
            menu.add_separator()
        menu.add_command(label="Add org...", command=self.add_org, state="disabled" if busy else "normal")
        menu.add_command(label="Create new org...", command=self.create_vault, state="disabled" if busy else "normal")
        menu.add_separator()
        menu.add_command(label="Exit", command=self._on_close)

    def _org_flag(self):
        flag = tk.StringVar(master=self, value=self.org or "")
        self.__dict__.setdefault("_menu_flags", []).append(flag)
        return flag

    def _fill_vault_menu(self, menu):
        menu.add_command(label="Refresh", accelerator="F5", command=self.refresh)
        menu.add_command(label="Get Latest", command=self.get_latest)
        menu.add_command(label="Download All...", command=self.download_all)
        menu.add_command(label="Update file rules...", command=self.update_file_rules,
                         state="normal" if self.file_rules_outdated else "disabled")
        menu.add_separator()
        menu.add_command(label="New Part...", command=self.new_part)
        menu.add_command(label="New Assembly...", command=self.new_assembly)
        menu.add_command(label="Import...", command=self.import_cad)
        menu.add_command(label="Import COTS...", command=self.import_cots)

    def _fill_view_menu(self, menu):
        screen = tk.StringVar(master=self, value=self.screen)
        self._menu_flags_keep(screen)
        for name, label, keys in (("parts", "Parts", "Ctrl+1"), ("tasks", "Workflows", "Ctrl+2"),
                                  ("ecos", "ECOs", "Ctrl+3"), ("team", "Team", "Ctrl+4")):
            menu.add_radiobutton(label=label, value=name, variable=screen, accelerator=keys,
                                 command=lambda name=name: self.show_screen(name))
        menu.add_separator()
        menu.add_checkbutton(label="Sidebar names", variable=self._menu_flag(not self.sidebar_collapsed),
                             command=lambda: self.set_sidebar_collapsed(not self.sidebar_collapsed, chosen=True))
        menu.add_checkbutton(label="Details pane", variable=self._menu_flag(self.details_shown()),
                             command=lambda: self.set_details_pane(not self.details_shown()))
        menu.add_checkbutton(label="Log", variable=self._menu_flag(self.log_shown), command=self.toggle_log)
        menu.add_separator()
        columns = menu_bar.dark_menu(menu)
        self._fill_columns_menu(columns)
        menu.add_cascade(label="Columns", menu=columns)
        sizes = menu_bar.dark_menu(menu)
        size = tk.IntVar(master=self, value=self.text_size)
        self._menu_flags_keep(size)
        for percent in ui_scale.TEXT_SIZES:
            sizes.add_radiobutton(label=f"{percent}%", value=percent, variable=size,
                                  command=lambda percent=percent: self.apply_text_size(percent))
        sizes.add_separator()
        sizes.add_command(label="Larger", accelerator="Ctrl+=", command=lambda: self.step_text_size(1))
        sizes.add_command(label="Smaller", accelerator="Ctrl+-", command=lambda: self.step_text_size(-1))
        sizes.add_command(label="Reset", accelerator="Ctrl+0", command=lambda: self.step_text_size(0))
        menu.add_cascade(label="Text size", menu=sizes)

    def _menu_flags_keep(self, variable):
        self.__dict__.setdefault("_menu_flags", []).append(variable)

    def _fill_help_menu(self, menu):
        menu.add_command(label="Status icons...", command=lambda: legend_dialog.LegendDialog(self, self.icons))
        menu.add_command(label="Check for updates...", command=self.check_for_updates)
        menu.add_separator()
        menu.add_command(label="About Litterbox", command=self.show_about)

    def show_about(self):
        messagebox.showinfo("About Litterbox", f"Litterbox {version.display()}\n\nShared vault check-in / check-out "
                                               "for CAD files, on Git and Git LFS.", parent=self)

    # -- the right-click menu -------------------------------------------------------------------------------------
    def _on_right_click(self, event):
        """Right-click a part: if its box isn't ticked, it becomes the only ticked part (so it is plain what the
        menu acts on), then the menu shows the actions."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        if iid not in self.ticked:
            self._set_ticks(list(self.ticked), False)
            self._set_ticks([iid], True)
        menu = menu_bar.dark_menu(self)
        count = len(self._ticked_pns())
        menu.add_command(label=f"Acting on {count} ticked part{'s' if count != 1 else ''}", state="disabled")
        menu.add_separator()
        self._fill_actions(menu, EVERYDAY_MENU + (None,) + OPEN_MENU + (None,) + self._lifecycle_entries())
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
