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

COLUMNS = ("Level", "Part number", "Rev", "Qty", "Total qty", "Name", "Description", "Material", "Status", "COTS",
           "Reference state", "Supplier", "Supplier part number", "Unit cost", "Total cost", "Lead time (days)")
TOTAL_LABEL = "Total cost of the assembly"
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def default_name(pn, revision, mode):
    """'HCR-00042-001_A BOM (indented).csv'."""
    return f"{filenames.file_stem(pn, revision)} BOM ({bom.MODE_LABEL[mode].lower()}).csv"


def safe_cell(value):
    """Text a spreadsheet shows as it is: one starting like a formula (=, +, -, @) gets a ' in front, so a name
    or supplier typed into a record can never run as a formula when the file is opened."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def _number(value):
    return "" if value is None else str(value)


def headings(currency=None):
    """The heading row: the cost columns say the team's currency ('Unit cost (USD)'). The cells stay plain numbers,
    so a spreadsheet can add them up."""
    return [f"{name} ({currency})" if currency and name in ("Unit cost", "Total cost") else name for name in COLUMNS]


def rows(found, cost=None, currency=None):
    """The table: a heading row, then one row per BomLine. Qty is how many its parent uses, Total qty how many
    the whole assembly needs; both are empty when not counted. Total cost is unit cost x Total qty. With `cost` (a
    bom.CostSummary of the whole assembly) a last row gives its total."""
    table = [headings(currency)]
    for line in found:
        table.append([str(line.level) if line.level else "", str(line.pn), line.revision,
                      _number(line.quantity), _number(line.total), line.name,
                      line.description, line.material, line.status.replace("_", " "), "Yes" if line.cots else "",
                      line.state_text + (" (uses an assembly above it)" if line.loop else ""),
                      line.field(purchasing_info.SUPPLIER), line.field(purchasing_info.SUPPLIER_PN),
                      line.field(purchasing_info.UNIT_COST), _number(bom.line_cost(line)),
                      line.field(purchasing_info.LEAD_TIME_DAYS)])
    if cost is not None and (cost.priced or cost.no_quantity):
        total = [""] * len(COLUMNS)
        total[COLUMNS.index("Name")] = TOTAL_LABEL + ("" if not (cost.no_cost or cost.no_quantity) else
                                                      " (some parts have no unit cost or count)")
        total[COLUMNS.index("Total cost")] = str(cost.total)
        table.append(total)
    return table


def write(path, found, litterbox_root, cost=None, currency=None):
    """Write the BOM lines to `path` (a .csv in a folder outside Litterbox and every repository), with the
    assembly's total cost last when `cost` is given. Returns the path written."""
    path = Path(path)
    if path.suffix.lower() != ".csv":
        path = path.with_name(path.name + ".csv")
    folder = export_folder.check(path.parent, litterbox_root)
    return write_in_vault(folder / path.name, found, cost, currency)


def write_in_vault(path, found, cost=None, currency=None):
    """Write the BOM lines to `path` with no check on the folder: the copy a released assembly revision keeps in
    the vault (parts/release_bom.py). Everything else goes through write(). Returns the path written."""
    path = Path(path)
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as out:     # the BOM mark makes Excel read UTF-8
            writer = csv.writer(out)
            for row in rows(found, cost, currency):
                writer.writerow([safe_cell(cell) for cell in row])
    except OSError as e:
        raise export_folder.ExportError(f"The BOM could not be written to {path}: {e}") from None
    return path
