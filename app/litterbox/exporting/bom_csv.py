"""
bom_csv.py - writing a BOM (references/bom.py) as a spreadsheet file (.csv, which Excel and every other
spreadsheet program open). It goes to a folder outside the vault (export_folder.check), as a copy: writing it again
makes a new file, or replaces the one picked.
"""

import csv
from pathlib import Path

from litterbox.core import filenames
from litterbox.exporting import export_folder
from litterbox.records import purchasing_info
from litterbox.references import bom

COLUMNS = ("Level", "Part number", "Rev", "Name", "Description", "Status", "COTS", "Reference state",
           "Supplier", "Supplier part number", "Unit cost", "Lead time (days)")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def default_name(pn, revision, mode):
    """'HCR-00042-001_A BOM (indented).csv'."""
    return f"{filenames.file_stem(pn, revision)} BOM ({bom.MODE_LABEL[mode].lower()}).csv"


def safe_cell(value):
    """Text a spreadsheet shows as it is: one starting like a formula (=, +, -, @) gets a ' in front, so a name
    or supplier typed into a record can never run as a formula when the file is opened."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def rows(found):
    """The table: a heading row, then one row per BomLine."""
    table = [list(COLUMNS)]
    for line in found:
        table.append([str(line.level) if line.level else "", str(line.pn), line.revision, line.name,
                      line.description, line.status.replace("_", " "), "Yes" if line.cots else "",
                      line.state_text + (" (uses an assembly above it)" if line.loop else ""),
                      line.field(purchasing_info.SUPPLIER), line.field(purchasing_info.SUPPLIER_PN),
                      line.field(purchasing_info.UNIT_COST), line.field(purchasing_info.LEAD_TIME_DAYS)])
    return table


def write(path, found, litterbox_root):
    """Write the BOM lines to `path` (a .csv in a folder outside Litterbox and every repository). Returns the
    path written."""
    path = Path(path)
    if path.suffix.lower() != ".csv":
        path = path.with_name(path.name + ".csv")
    folder = export_folder.check(path.parent, litterbox_root)
    path = folder / path.name
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as out:     # the BOM mark makes Excel read UTF-8
            writer = csv.writer(out)
            for row in rows(found):
                writer.writerow([safe_cell(cell) for cell in row])
    except OSError as e:
        raise export_folder.ExportError(f"The BOM could not be written to {path}: {e}") from None
    return path
