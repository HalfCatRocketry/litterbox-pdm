"""
home_actions.py - changing folders from the window (home_view.py shows them): Home's right-click menu (New Folder,
Rename, Delete, Add Parts... (a search window), Put the ticked items here, Remove from this folder, and the part
actions), dragging items and folders between folders, double-clicking an item, and Add to Folder... from the Part
menu, the Documents screen and the ECOs screen. Items can go in a folder or straight in a top (Personal, Team, a
project): folder id "" (folder_model.ROOT).

A Personal change is made at once on this computer. A Team or project change shows at once and is uploaded in the
background (folders/folder_store.py); who may make it is folders/folder_access.py.
"""

from tkinter import messagebox

from litterbox.errors import LitterboxError
from litterbox.folders import folder_access
from litterbox.folders import folder_actions
from litterbox.folders import folder_model
from litterbox.folders import folder_store
from litterbox.folders.folder_model import FolderError
from litterbox.gui.dialogs import folder_picker_dialog
from litterbox.gui.dialogs.workflow import part_picker_dialog
from litterbox.gui.logic import list_view
from litterbox.gui.logic import folder_text
from litterbox.gui.widgets import menu_bar
from litterbox.team import guarded_push

DRAG_START = 6              # pixels the mouse moves before a press becomes a drag


class HomeActions:
    """Changing folders. One part of the main window (App)."""

    # -- where and who ------------------------------------------------------------------------------------------
    def _project_named(self, name):
        return next((p for p in self.home_projects if p.name.lower() == str(name).lower()), None)

    def _may_change_place(self, place):
        if place is None:
            return False, "Choose Personal, Team or one of your projects."
        project = self._project_named(place.project) if place.scope == folder_access.PROJECT else None
        return folder_access.may_change(self.identity, place.scope, project)

    def _tree_of(self, place):
        return folder_text.tree_for(self.home_trees, place, self.home_personal)

    def _places(self):
        """[(Place, title, tree)] for every tree Home shows."""
        found = [(folder_actions.Place(folder_access.PERSONAL), folder_text.PERSONAL_TITLE, self.home_personal),
                 (folder_actions.Place(folder_access.TEAM), folder_text.TEAM_TITLE, self.home_trees.team)]
        for project in sorted(folder_access.shown_projects(self.identity, self.home_projects),
                              key=lambda p: p.name.lower()):
            place = folder_actions.Place(folder_access.PROJECT, project.name)
            found.append((place, project.name, self._tree_of(place)))
        return found

    # -- making a change ----------------------------------------------------------------------------------------
    def change_folders(self, place, ops, message):
        """Make these folder changes: Personal ones now, the others shown now and uploaded in the background."""
        allowed, why = self._may_change_place(place)
        if not allowed:
            self._say(why, "warn")
            return
        ops = [op for op in ops if op]
        if not ops:
            return
        if place.scope == folder_access.PERSONAL:
            try:
                folder_actions.apply_change(self.repo(), place, ops, message, personal_path=self.personal_path())
            except OSError as e:
                messagebox.showerror("Folders", f"Your Personal folders couldn't be saved: {e}", parent=self)
                return
            self._load_personal()
            self._render_home()
            self._say(f"Folders: {message}")
            return
        tree = self._tree_of(place)
        if place.scope == folder_access.PROJECT and not any(n.lower() == place.project.lower()
                                                            for n in self.home_trees.projects):
            tree = self.home_trees.projects.setdefault(place.project, {})
        for op in ops:                                     # shown now; the upload follows
            folder_model.apply(tree, op)
        self._render_home()
        repo = self.repo()

        def work():
            try:
                folder_actions.apply_change(repo, place, ops, message, push=guarded_push.push)
            except LitterboxError as e:                   # show the folders as they really are, then say why
                return folder_store.load(repo), str(e)
            return folder_store.load(repo), ""

        def done(result):
            self.home_trees, problem = result
            self._render_home()
            if problem:
                self._say("The folder change wasn't uploaded.", "warn")
                messagebox.showwarning("Folders", problem, parent=self)

        self.run_task(work, f"Folders: {message}", on_success=done, refresh=False, label="Saving folders")

    def _try(self, make):
        """The change make() gives, or None after saying why it can't be made."""
        try:
            return make()
        except FolderError as e:
            messagebox.showwarning("Folders", str(e), parent=self)
            return None

    # -- the menu -----------------------------------------------------------------------------------------------
    def _on_home_right_click(self, event):
        iid = self.home.identify_row(event.y)
        row = self.home_rows.get(iid)
        if row is None:
            return
        self.home.selection_set(iid)
        menu = menu_bar.dark_menu(self)
        may, why = self._may_change_place(row.place)
        if row.place is None:
            menu.add_command(label=folder_text.no_projects_text() if not folder_access.shown_projects(
                self.identity, self.home_projects) else "Each of your projects has folders here.",
                **menu_bar.entry_options(False))
        elif not may:
            menu.add_command(label=why, **menu_bar.entry_options(False))
            menu.add_separator()
        if row.kind in ("top", "folder") and row.place is not None:
            menu.add_command(label="New Folder...", **menu_bar.entry_options(may, lambda: self.new_folder(row)))
        if row.kind == "folder":
            menu.add_command(label="Rename...", **menu_bar.entry_options(may, lambda: self.rename_folder(row)))
            menu.add_command(label="Delete Folder...", **menu_bar.entry_options(may, lambda: self.delete_folder(row)))
        if row.kind in ("top", "folder") and row.place is not None:
            count = len(self.ticked)
            menu.add_separator()
            menu.add_command(label="Add Parts...", **menu_bar.entry_options(may, lambda: self.add_parts(row)))
            menu.add_command(label=f"Put the {count} ticked here" if count else "Put the ticked here (none ticked)",
                             **menu_bar.entry_options(may and count > 0, lambda: self.put_ticked(row)))
        if row.kind == "item":
            self._item_menu(menu, row, may)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _item_menu(self, menu, row, may):
        kind, _number = folder_text.parse_item(row.item)
        menu.add_command(label="Details...", command=lambda: self._open_home_item(row))
        menu.add_command(label="Remove from This Folder" if row.folder else "Remove from Here",
                         **menu_bar.entry_options(may, lambda: self.remove_item(row)))
        if kind in ("part", "document") and self._home_highlighted():
            if row.item not in self.ticked:                   # like the parts list: it becomes the only ticked one
                self._set_home_ticks(list(self.ticked), False)
                self._set_home_ticks([row.item], True)
            menu.add_separator()
            self._fill_actions(menu, self._home_part_menu())

    def new_folder(self, row):
        name = self._ask("Name of the new folder:", "New Folder")
        if name is None:
            return
        parent = row.folder if row.kind == "folder" else ""
        op = self._try(lambda: folder_actions.add_folder(self._tree_of(row.place), parent, name))
        if op:
            self.change_folders(row.place, [op], f"{op['name']}: added")

    def rename_folder(self, row):
        name = self._ask(f"New name for {row.text}:", "Rename Folder")
        if name is None:
            return
        op = self._try(lambda: folder_actions.rename_folder(self._tree_of(row.place), row.folder, name))
        if op:
            self.change_folders(row.place, [op], f"{row.text} renamed to {op['name']}")

    def delete_folder(self, row):
        tree = self._tree_of(row.place)
        inside = len(folder_model.below(tree, row.folder)) - 1
        more = f" and the {inside} folder{'s' if inside != 1 else ''} in it" if inside else ""
        if not messagebox.askyesno("Delete Folder", f"Delete {row.text}{more}? What they list isn't touched: only "
                                                    "the folders go.", parent=self):
            return
        op = self._try(lambda: folder_actions.delete_folder(tree, row.folder))
        if op:
            self.change_folders(row.place, [op], f"{row.text}: deleted")

    def put_ticked(self, row):
        op = self._try(lambda: folder_actions.put_items(self._tree_of(row.place), row.folder, sorted(self.ticked)))
        if op:
            self.change_folders(row.place, [op], f"{len(op['items'])} added to {row.text}")
        else:
            self._say("Everything ticked is in that folder already.")

    def add_parts(self, row):
        """Add Parts...: a search window of every part and document not in this folder (or top) yet."""
        holder = folder_model.holder(self._tree_of(row.place), row.folder)
        if holder is None:
            self._say("That folder isn't there any more. Someone may have just deleted it.", "warn")
            return
        have = set(holder.items)
        rows = [r for r in self.rows_by_pn.values() if str(r.pn) not in have]
        rows = [rows[i] for i in list_view.sort_order([str(r.pn) for r in rows])]
        chosen = part_picker_dialog.PartPickerDialog(
            self, rows, heading=f"Add parts to {row.text}",
            empty="Every part and document in this vault is here already.").show()
        if not chosen:
            return
        op = self._try(lambda: folder_actions.put_items(self._tree_of(row.place), row.folder,
                                                         [str(pn) for pn in chosen]))
        if op:
            self.change_folders(row.place, [op], f"{len(op['items'])} added to {row.text}")

    def remove_item(self, row):
        op = self._try(lambda: folder_actions.take_items(self._tree_of(row.place), row.folder, [row.item]))
        if op:
            self.change_folders(row.place, [op], f"{row.item} taken out of a folder")

    def _open_home_item(self, row):
        kind, number = folder_text.parse_item(row.item)
        if kind == "eco":
            self.view_eco(number)
        elif kind in ("part", "document") and number in self.rows_by_pn:
            self.show_history()
        else:
            self._say(f"{row.item} isn't in this vault (or not in your copy of it).", "warn")

    def _on_home_double_click(self, event):
        row = self.home_rows.get(self.home.identify_row(event.y))
        if row is not None and row.kind == "item" and "image" not in str(self.home.identify_element(event.x, event.y)):
            self._open_home_item(row)
            return "break"
        return None

    # -- dragging -----------------------------------------------------------------------------------------------
    def _on_home_drag(self, event):
        drag = getattr(self, "_drag", None)
        if not drag:
            return
        if not drag["moved"] and abs(event.x - drag["x"]) + abs(event.y - drag["y"]) < self._px(DRAG_START):
            return
        drag["moved"] = True
        self.home.configure(cursor="fleur")

    def _on_home_drop(self, event):
        drag, self._drag = getattr(self, "_drag", None), None
        self.home.configure(cursor="")
        if not drag or not drag["moved"]:
            return
        source = self.home_rows.get(drag["source"])
        target = self.home_rows.get(self.home.identify_row(event.y))
        if source is None or target is None or target.place is None:
            return
        if target.kind == "item":                       # onto an item: into the folder (or top) it is in
            holder = (folder_text.folder_iid(target.place, target.folder) if target.folder
                      else folder_text.top_iid(target.place))
            target = self.home_rows.get(holder, target)
        if source.kind == "item":
            self._drop_item(source, target)
        elif source.kind == "folder":
            self._drop_folder(source, target)

    def _drop_item(self, source, target):
        if target.kind not in ("folder", "top") or target.place is None:
            self._say("Drop it on a folder.", "warn")
            return
        if target.place == source.place and target.folder == source.folder:
            return
        tree = self._tree_of(target.place)
        put = self._try(lambda: folder_actions.put_items(tree, target.folder, [source.item]))
        if target.place != source.place:                 # into another tree: a copy, the original stays
            if put:
                self.change_folders(target.place, [put], f"{source.item} added to {target.text}")
            return
        take = self._try(lambda: folder_actions.take_items(tree, source.folder, [source.item]))
        self.change_folders(target.place, [take, put], f"{source.item} moved to {target.text}")

    def _drop_folder(self, source, target):
        if target.place != source.place:
            self._say("A folder moves only within Personal, the Team folders or one project's.", "warn")
            return
        parent = target.folder if target.kind == "folder" else ""
        op = self._try(lambda: folder_actions.move_folder(self._tree_of(source.place), source.folder, parent))
        if op:
            self.change_folders(source.place, [op], f"{source.text} moved")

    # -- Add to Folder... ---------------------------------------------------------------------------------------
    def add_to_folder(self, items=None):
        """Put these items (default: the ticked parts, or the highlighted one) in a folder chosen from a list."""
        if items is None:
            items = [str(number) for number in self._selected_pns("add_to_folder")]
        if not items:
            self._say("Tick what to put in a folder first (or click one).", "warn")
            return
        if self.home_shown is False:
            self._load_personal()
        places = [(place, title, tree) for place, title, tree in self._places() if self._may_change_place(place)[0]]
        chosen = folder_picker_dialog.FolderPickerDialog(self, places, len(items)).show()
        if not chosen:
            return
        place, folder_id, new_ops = chosen
        put = {"op": "put", "folder": folder_id, "items": [str(item) for item in items]}
        if not new_ops:
            put = self._try(lambda: folder_actions.put_items(self._tree_of(place), folder_id, items))
            if put is None:
                self._say("Those are all in that folder already.")
                return
        self.change_folders(place, list(new_ops) + [put], f"{len(items)} added to a folder")
