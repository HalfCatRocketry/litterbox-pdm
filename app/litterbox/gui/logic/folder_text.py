"""
folder_text.py - Home in words (folders/: Personal, Team and Projects): its rows, top to bottom, the name of each
thing a folder points at, and what a row's id means.

    rows = folder_text.home_rows(personal, trees, projects, describe, search="brack")
    # [HomeRow]: three tops (Personal, Team, Projects, with a top per project under Projects), then folders and the
    # items in them. An item reads "HCR-00042-001   Bracket" (one line: its number, then its name).

Within a top or a folder, the folders come first (by name), then the items: parts, documents, ECOs, each by number.
An item at the top of a tree has the folder id "" (folder_model.ROOT).

A row's id says where it is, so a click can be traced back: "top:team", "top:project:Rover", "f|<place>|<folder>",
"i|<place>|<folder>|<item>" (place: personal, team, or project:<name>).
"""

import re
from dataclasses import dataclass

from litterbox.core import doc_number
from litterbox.core import part_number
from litterbox.folders import folder_access
from litterbox.folders import folder_model
from litterbox.folders.folder_actions import Place

PERSONAL_TITLE, TEAM_TITLE, PROJECTS_TITLE = "Personal", "Team", "Projects"
ECO = re.compile(r"^ECO-\d+$", re.IGNORECASE)
GAP = "   "


@dataclass
class HomeRow:
    iid: str
    parent: str                 # the row it sits under ("" for a top)
    kind: str                   # "top", "folder" or "item"
    text: str
    place: Place = None         # the tree it belongs to (None for the Projects top)
    folder: str = ""            # its folder's id (a folder's own id; an item's folder)
    item: str = ""              # what an item points at


def place_key(place):
    return place.scope if place.scope != folder_access.PROJECT else f"{folder_access.PROJECT}:{place.project}"


def place_of(key):
    if key.startswith(folder_access.PROJECT + ":"):
        return Place(folder_access.PROJECT, key.split(":", 1)[1])
    return Place(key)


def top_iid(place):
    return f"top:{place_key(place)}"


def folder_iid(place, folder_id):
    return f"f|{place_key(place)}|{folder_id}"


def item_iid(place, folder_id, item):
    return f"i|{place_key(place)}|{folder_id}|{item}"


def parse_iid(iid):
    """(kind, Place or None, folder id, item) for a row id."""
    if iid == "top:projects":
        return "top", None, "", ""
    if iid.startswith("top:"):
        return "top", place_of(iid[4:]), "", ""
    parts = iid.split("|", 3)
    if parts[0] == "f" and len(parts) == 3:
        return "folder", place_of(parts[1]), parts[2], ""
    if parts[0] == "i" and len(parts) == 4:
        return "item", place_of(parts[1]), parts[2], parts[3]
    return "", None, "", ""


def parse_item(text):
    """("part", PN), ("document", DocNumber), ("eco", "ECO-0003") or ("", text) for what an item points at."""
    text = str(text or "").strip()
    pn = part_number.try_parse(text)
    if pn is not None:
        return "part", pn
    if ECO.match(text):
        return "eco", text.upper()
    try:
        return "document", doc_number.parse(text)
    except Exception:
        return "", text


def item_label(item, name):
    """An item's line: its number, then its name."""
    return f"{item}{GAP}{name}" if name else str(item)


ITEM_ORDER = ("part", "document", "eco")


def item_sort_key(item):
    """Parts, then documents, then ECOs (then anything else), each by number."""
    kind, _number = parse_item(item)
    return (ITEM_ORDER.index(kind) if kind in ITEM_ORDER else len(ITEM_ORDER), str(item).upper())


def _matches(text, search):
    return not search or search.lower() in text.lower()


def _tree_rows(place, tree, describe, search):
    """The rows of one tree under its top, leaving out what the search doesn't find (a folder stays when its name
    or anything in it does)."""
    def items_of(folder_id, parent_iid):
        holder = folder_model.holder(tree, folder_id)
        items = [HomeRow(item_iid(place, folder_id, item), parent_iid, "item", item_label(item, describe(item)),
                         place, folder_id, item) for item in sorted(holder.items, key=item_sort_key)]
        return [row for row in items if _matches(row.text, search)]

    def visit(parent_id, parent_iid):
        kept = []
        for folder in folder_model.children(tree, parent_id):
            iid = folder_iid(place, folder.id)
            inner = visit(folder.id, iid) + items_of(folder.id, iid)
            if inner or _matches(folder.name, search):
                kept += [HomeRow(iid, parent_iid, "folder", folder.name, place, folder.id)] + inner
        return kept

    top = top_iid(place)
    return visit(folder_model.ROOT, top) + items_of(folder_model.ROOT, top)


def home_rows(personal, trees, projects, describe, search=""):
    """Every row of Home: `personal` is your tree, `trees` the vault's (folder_store.Trees), `projects` those to
    show (folder_access.shown_projects), `describe(item)` an item's name ("" if unknown)."""
    search = " ".join(str(search or "").split())
    rows = []
    for place, title, tree in ((Place(folder_access.PERSONAL), PERSONAL_TITLE, personal),
                               (Place(folder_access.TEAM), TEAM_TITLE, trees.team)):
        rows.append(HomeRow(top_iid(place), "", "top", title, place))
        rows += _tree_rows(place, tree, describe, search)
    rows.append(HomeRow("top:projects", "", "top", PROJECTS_TITLE))
    for project in sorted(projects, key=lambda p: p.name.lower()):
        place = Place(folder_access.PROJECT, project.name)
        rows.append(HomeRow(top_iid(place), "top:projects", "top", project.name, place))
        rows += _tree_rows(place, tree_for(trees, place), describe, search)
    return rows


def tree_for(trees, place, personal=None):
    """The tree of a place: `personal` for Personal, else the vault's (folder_store.Trees)."""
    if place.scope == folder_access.PERSONAL:
        return personal if personal is not None else {}
    if place.scope == folder_access.TEAM:
        return trees.team
    return next((tree for name, tree in trees.projects.items() if name.lower() == place.project.lower()), {})


def no_projects_text():
    return "No projects of yours yet. A project's folders show here once you are its Lead or one of its members."
