"""
list_columns.py - the parts list's columns: what each shows, which are shown (the Columns menu, remembered in
settings.yaml as `list_columns`), their widths, and which ones the search box can look in.

The first column, with the tick box and the status icon, is always there and isn't listed here.
"""

from dataclasses import dataclass

from litterbox.gui.logic import list_view
from litterbox.gui.logic import material_text


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    width: int                      # starting width at 100% display scaling, in pixels
    shown: bool                     # shown unless the person has chosen otherwise
    fit: bool = False               # long text is cut to the width with "..." (the full text is in the tooltip)
    stretch: bool = False           # takes up spare width when the window grows

    def text(self, row):
        """What the column shows for a part (a PartStatus)."""
        return _VALUES[self.key](row)[0]

    def search_values(self, row):
        """Everything the search box compares for this column (a part number matches as HCR-00007-001 or 00007-001)."""
        return _VALUES[self.key](row)


_VALUES = {
    "pn": lambda row: (row.pn.short, str(row.pn)),
    "name": lambda row: (row.name or "",),
    "description": lambda row: (row.description or "",),
    "project": lambda row: (row.project or "",),
    "rev": lambda row: (row.revision or "",),
    "files": lambda row: (list_view.file_types(row.files),),
    "cots": lambda row: ("Yes" if row.cots else "",),
    "kind": lambda row: ("Non-CAD" if getattr(row, "noncad", False) else "CAD",),
    "state": lambda row: (row.state or "",),
    "locked_by": lambda row: (row.locked_by if row.kind in ("mine", "theirs") else "",),
    "released": lambda row: (row.released_revision or "",),
    "import_path": lambda row: (row.import_path or "",),
    "material": lambda row: (material_text.column_text(row),),
}


COLUMNS = (
    Column("pn", "Part number", 120, True),
    Column("rev", "Rev", 48, True),
    Column("name", "Name", 220, True, fit=True),
    Column("description", "Description", 260, True, fit=True, stretch=True),
    Column("project", "Project", 120, False, fit=True),
    Column("files", "Files", 80, True),
    Column("kind", "Kind", 70, True),
    Column("cots", "COTS", 56, False),
    Column("state", "Status", 230, False, fit=True),
    Column("locked_by", "Checked out by", 130, False, fit=True),
    Column("released", "Released rev", 96, False),
    Column("import_path", "Imported from", 240, False, fit=True),
    Column("material", "Material", 160, False, fit=True),
)


BY_KEY = {column.key: column for column in COLUMNS}


ALL_COLUMNS = "All columns"


def shown_keys(setting):
    """The columns to show, in the list's order, from the `list_columns` setting (a list of keys). A missing or
    unusable setting gives the defaults. The part number is always shown."""
    if isinstance(setting, (list, tuple)):
        wanted = {str(key) for key in setting}
        keys = [column.key for column in COLUMNS if column.key in wanted or column.key == "pn"]
        if len(keys) > 1 or wanted == {"pn"}:
            return keys
    return [column.key for column in COLUMNS if column.shown]


def toggled(keys, key):
    """The shown columns after switching one on or off (in the list's order). The part number stays."""
    if key == "pn" or key not in BY_KEY:
        return list(keys)
    chosen = set(keys) ^ {key}
    return [column.key for column in COLUMNS if column.key in chosen or column.key == "pn"]


def search_choices(keys):
    """The entries of the 'search in' box: every column, then the shown ones."""
    return [ALL_COLUMNS] + [BY_KEY[key].title for key in keys]


def search_values(row, keys):
    """Every value the search box compares for a part, in the given columns."""
    return [value for key in keys for value in BY_KEY[key].search_values(row)]


def search_keys(choice):
    """Which columns a 'search in' choice looks at. 'All columns' looks in every column, shown or not."""
    for column in COLUMNS:
        if column.title == choice:
            return [column.key]
    return [column.key for column in COLUMNS]
