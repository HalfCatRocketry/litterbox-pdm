"""
folder_actions.py - changing folders (Home in the main window): the change each action makes, checked against the
tree it is for, and making it in the right place: Personal folders in their file on this computer
(folders/personal_folders.py), Team and project folders as a new change in the vault (folders/folder_store.py).

    place = folder_actions.Place(folder_access.TEAM)            # or Place(PROJECT, "Rover"), Place(PERSONAL)
    op = folder_actions.add_folder(tree, parent_id, "Brackets")    # FolderError if it can't be done
    folder_actions.apply_change(repo, place, [op], "Brackets: added", personal_path=..., push=guarded_push.push)

Who may change which tree is folders/folder_access.py; the window asks it first.
"""

from dataclasses import dataclass

from litterbox.folders import folder_access
from litterbox.folders import folder_model
from litterbox.folders import folder_store
from litterbox.folders import personal_folders
from litterbox.folders.folder_model import FolderError


@dataclass(frozen=True)
class Place:
    scope: str                  # folder_access.PERSONAL, TEAM or PROJECT
    project: str = ""           # the project's name, for PROJECT


def _folder(tree, folder_id):
    folder = tree.get(folder_id) if folder_id != folder_model.ROOT else None
    if folder is None:
        raise FolderError("That folder isn't there any more. Someone may have just deleted it.")
    return folder


def add_folder(tree, parent, name):
    name = folder_model.check_name(name)
    if parent:
        _folder(tree, parent)
    if folder_model.name_taken(tree, parent, name):
        raise FolderError(f"There is already a folder called {name} there.")
    return {"op": "add", "folder": folder_model.new_id(), "parent": parent or "", "name": name}


def rename_folder(tree, folder_id, name):
    folder, name = _folder(tree, folder_id), folder_model.check_name(name)
    if folder_model.name_taken(tree, folder.parent, name, but=folder_id):
        raise FolderError(f"There is already a folder called {name} there.")
    return {"op": "rename", "folder": folder_id, "name": name}


def move_folder(tree, folder_id, parent):
    folder = _folder(tree, folder_id)
    if parent and parent in folder_model.below(tree, folder_id):
        raise FolderError("A folder can't go inside itself.")
    if parent:
        _folder(tree, parent)
    if folder_model.name_taken(tree, parent, folder.name, but=folder_id):
        raise FolderError(f"There is already a folder called {folder.name} there.")
    return {"op": "move", "folder": folder_id, "parent": parent or ""}


def delete_folder(tree, folder_id):
    _folder(tree, folder_id)
    return {"op": "delete", "folder": folder_id}


def _holder(tree, folder_id):
    """What holds a folder's items: the folder, or the top of the tree for ROOT."""
    return folder_model.holder(tree, folder_id) if folder_id == folder_model.ROOT else _folder(tree, folder_id)


def put_items(tree, folder_id, items):
    """The change that adds these items (those not in the folder, or at the top for ROOT, already), or None if
    they all are."""
    folder = _holder(tree, folder_id)
    new = [str(item) for item in dict.fromkeys(items) if str(item) not in folder.items]
    return {"op": "put", "folder": folder_id, "items": new} if new else None


def take_items(tree, folder_id, items):
    folder = _holder(tree, folder_id)
    gone = [str(item) for item in items if str(item) in folder.items]
    return {"op": "take", "folder": folder_id, "items": gone} if gone else None


def apply_change(repo, place, ops, message, personal_path=None, push=None):
    """Make these changes to the place's tree: Personal ones in `personal_path`, the others as one change in the
    vault, uploaded with `push`."""
    ops = [op for op in ops if op]
    if not ops:
        return
    if place.scope == folder_access.PERSONAL:
        tree = personal_folders.load(personal_path)
        for op in ops:
            folder_model.apply(tree, op)
        personal_folders.save(personal_path, tree)
        return
    folder_store.save_change(repo, place.scope, place.project, ops, message, push)
