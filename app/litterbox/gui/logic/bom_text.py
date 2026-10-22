"""
bom_text.py - the BOM tab's table and the line above it (see references/bom.py), the lines you may take off it and
the parts Add item... offers (parts/bom_items.py), and the status line after a BOM is exported.
"""

from litterbox.core import currency as currencies
from litterbox.core.filenames import file_stem
from litterbox.records import purchasing_info
from litterbox.references import bom

COLUMNS = (("pn", "Part", 130), ("rev", "Rev", 50), ("qty", "Qty", 50), ("name", "Name", 160),
           ("material", "Material", 120), ("supplier", "Supplier", 110), ("cost", "Unit cost", 70), ("ext", "Total cost", 80), ("lead", "Lead time", 70),
           ("state", "State", 160))

INDENT = "    "


def quantity(line):
    """The Qty column: how many its parent uses (in "every part once", how many in all); '?' if not counted."""
    return "?" if line.quantity is None else str(line.quantity)


def table(found, mode, currency=None):
    """[(iid, values)] for the tab. In an indented BOM the part number is pushed right by its level. Costs carry
    the team's currency symbol (core/currency.py)."""
    rows = []
    for number, line in enumerate(found):
        part = (INDENT * (line.level - 1) if mode == bom.INDENTED and line.level else "") + line.pn.short
        lead = line.field(purchasing_info.LEAD_TIME_DAYS)
        state = line.state_text + (" (loops back)" if line.loop else "") + (" (added by hand)" if line.added else "")
        rows.append((f"line{number}", (part, line.revision, quantity(line), line.name, line.material,
                                       line.field(purchasing_info.SUPPLIER),
                                       currencies.money(line.field(purchasing_info.UNIT_COST), currency),
                                       currencies.money(bom.line_cost(line), currency),
                                       f"{lead} days" if lead else "", state)))
    return rows


def removable(found):
    """{iid: stem} of the lines Remove can take off: those added by hand to the assembly itself (level 1)."""
    return {f"line{number}": file_stem(line.pn, line.revision) for number, line in enumerate(found)
            if line.added and line.level == 1}


def item_choices(rows, assembly_row):
    """The parts Add item... offers for an assembly (PartStatus rows): never itself or a void part, and for a CAD
    assembly only non-CAD parts (its CAD parts come from the model)."""
    kit = getattr(assembly_row, "noncad", False)
    return [row for row in rows if row.pn != assembly_row.pn and row.kind not in ("void", "error", "missing")
            and (kit or getattr(row, "noncad", False))]


def cost_text(summary, currency=None):
    """'total cost $1,234.50 (2 parts have no unit cost)', or '' when nothing in the BOM has a unit cost."""
    if summary is None or not (summary.priced or summary.no_quantity):
        return ""
    gaps = []
    if summary.no_cost:
        gaps.append(f"{summary.no_cost} part{'s have' if summary.no_cost != 1 else ' has'} no unit cost")
    if summary.no_quantity:
        gaps.append(f"{summary.no_quantity} {'are' if summary.no_quantity != 1 else 'is'} not counted")
    return f"total cost {currencies.money(summary.total, currency)}" + (f" ({', '.join(gaps)})" if gaps else "")


def note(found, is_assembly, outdated=False, counts_outdated=False, cost=None, currency=None):
    """The line above the table. `outdated`: its list of parts used is out of date; `counts_outdated`: only
    its quantities are (it was checked in without SolidWorks open, or before Litterbox counted parts). `cost` is
    the assembly's bom.CostSummary, `currency` the team's."""
    if not is_assembly:
        return "This revision uses no other parts, so it has no BOM."
    count = len(found)
    said = [f"{count} line{'s' if count != 1 else ''}"]
    if cost_text(cost, currency):
        said.append(cost_text(cost, currency))
    said += bom.problems(found)
    if outdated:
        said.append("its list of parts used is out of date. Update BOM reads it again and counts the parts")
    elif counts_outdated:
        said.append("its quantities need updating (it was checked in without SolidWorks open, or before "
                    "Litterbox counted parts). Update BOM counts them")
    return ". ".join(s[0].upper() + s[1:] for s in said) + "."


def update_button_text(can_start_solidworks):
    """What the Update BOM button's tooltip says."""
    if can_start_solidworks:
        return ("Read the assembly with SolidWorks and count its parts. If SolidWorks isn't open, Litterbox starts "
                "it out of sight and closes it afterwards.")
    return "SolidWorks isn't installed on this computer, so someone who has it must update this BOM."


def exported_text(path, count):
    return f"Exported a BOM of {count} line{'s' if count != 1 else ''} to {path}."
