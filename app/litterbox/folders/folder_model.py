"""
folder_model.py - folders: what a folder holds, and the changes that build a tree of them.

A folder has a name, a parent ("" for the top of its tree) and items: what it points at, as text ("HCR-00042-001",
"PROP-0001", "ECO-0003"). An item is only a pointer, so the same part can be in any number of folders, and removing
it from a folder, or deleting the folder, never touches the part.

There are three kinds of tree (Home in the main window): Personal (yours, kept on this computer:
folders/personal_folders.py), Team (the org's) and one per project (folders/folder_store.py keeps those two in the
vault, as changes nobody ever edits). A tree is built by applying changes in order:

    {op: add, folder: <id>, parent: <id or "">, name: Brackets}
    {op: rename, folder: <id>, name: Brackets, left}
    {op: move, folder: <id>, parent: <id or "">}        never into itself or below itself
    {op: delete, folder: <id>}                          and every folder below it
    {op: put, folder: <id>, items: [HCR-00042-001]}     added once, at the end
    {op: take, folder: <id>, items: [HCR-00042-001]}

Items can also sit at the top of a tree, outside every folder: put and take with folder "" (ROOT). The tree keeps
them in a holder under that key (parent None, so it is never one of the folders); an older Litterbox skips those
changes, as it does any change about a folder it doesn't have.

A change about a folder that is gone (someone deleted it at the same time) does nothing, so two people working at
once never break each other's tree.
"""

import secrets
from dataclasses import dataclass, field

NAME_MAX = 80
ROOT = ""                   # the top of a tree, as a place to put items
OPS = ("add", "rename", "move", "delete", "put", "take")


class FolderError(ValueError):
    """A change that can't be made (a bad name, a folder that isn't there)."""


@dataclass
class Folder:
    id: str
    name: str
    parent: str = ""
    items: list = field(default_factory=list)


def new_id():
    return secrets.token_hex(4)


def check_name(text):
    """The name tidied (spaces), or FolderError."""
    name = " ".join(str(text or "").split())
    if not name:
        raise FolderError("A folder needs a name.")
    if len(name) > NAME_MAX:
        raise FolderError(f"A folder's name can be at most {NAME_MAX} characters.")
    return name


def holder(tree, folder_id):
    """The folder that holds a folder's items (ROOT: the top's holder, empty if nothing is there yet), or None."""
    if folder_id == ROOT:
        return tree.get(ROOT) or Folder(ROOT, "", None)
    return tree.get(folder_id)


def folders(tree):
    """The folders of a tree (not the top's holder)."""
    return [f for f in tree.values() if f.id != ROOT]


def below(tree, folder_id):
    """The ids of a folder and every folder below it."""
    found, todo = [], [folder_id]
    while todo:
        current = todo.pop()
        if current in tree and current not in found:
            found.append(current)
            todo += [f.id for f in tree.values() if f.parent == current]
    return found


def apply(tree, op):
    """Make one change to `tree` ({id: Folder}). Returns True if it changed anything; a change that can't apply any
    more (its folder is gone, a move into itself) is skipped."""
    kind, folder_id = op.get("op"), str(op.get("folder") or "")
    if folder_id == ROOT:                               # the top holds items, nothing else
        if kind != "put" and not (kind == "take" and ROOT in tree):
            return False
        tree.setdefault(ROOT, Folder(ROOT, "", None))
    folder = tree.get(folder_id)
    if kind == "add":
        parent = str(op.get("parent") or "")
        if folder is not None or (parent and parent not in tree):
            return False
        tree[folder_id] = Folder(folder_id, str(op.get("name") or folder_id), parent)
        return True
    if folder is None:
        return False
    if kind == "rename":
        folder.name = str(op.get("name") or folder.name)
    elif kind == "move":
        parent = str(op.get("parent") or "")
        if (parent and parent not in tree) or (parent and parent in below(tree, folder_id)):
            return False
        folder.parent = parent
    elif kind == "delete":
        for gone in below(tree, folder_id):
            del tree[gone]
    elif kind == "put":
        folder.items += [str(item) for item in op.get("items") or [] if str(item) not in folder.items]
    elif kind == "take":
        gone = {str(item) for item in op.get("items") or []}
        folder.items = [item for item in folder.items if item not in gone]
    else:
        return False
    return True


def build(ops):
    """A tree from changes, in order."""
    tree = {}
    for op in ops:
        apply(tree, op)
    return tree


def children(tree, parent=""):
    """The folders directly in `parent` ("" for the top), by name."""
    return sorted((f for f in tree.values() if f.parent == parent), key=lambda f: (f.name.lower(), f.id))


def path_of(tree, folder_id):
    """["Top", "Inner", "Folder"]: the names from the top down to the folder."""
    names, current = [], tree.get(folder_id) if folder_id != ROOT else None
    while current is not None and len(names) <= len(tree):
        names.insert(0, current.name)
        current = tree.get(current.parent)
    return names


def name_taken(tree, parent, name, but=None):
    """True if `parent` already has a folder called `name` (capitals don't count), other than `but`."""
    return any(f.name.lower() == name.lower() and f.id != but for f in tree.values() if f.parent == parent)


def to_ops(tree):
    """Changes that build this tree from nothing (parents first): how a Personal tree is saved."""
    ops, placed = [], set()
    pending = folders(tree)
    while pending:
        ready = [f for f in pending if not f.parent or f.parent in placed]
        if not ready:                                  # a parent that isn't there: put the rest at the top
            ready = pending
            for folder in ready:
                folder.parent = ""
        for folder in ready:
            ops.append({"op": "add", "folder": folder.id, "parent": folder.parent, "name": folder.name})
            if folder.items:
                ops.append({"op": "put", "folder": folder.id, "items": list(folder.items)})
            placed.add(folder.id)
            pending.remove(folder)
    top = tree.get(ROOT)
    if top is not None and top.items:
        ops.append({"op": "put", "folder": ROOT, "items": list(top.items)})
    return ops
