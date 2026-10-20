"""
bom_text.py - the BOM tab's table and the line above it (see references/bom.py), and the status line after a BOM
is exported.
"""

from litterbox.records import purchasing_info
from litterbox.references import bom

COLUMNS = (("pn", "Part", 130), ("rev", "Rev", 40), ("name", "Name", 160), ("supplier", "Supplier", 110),
           ("cost", "Unit cost", 70), ("lead", "Lead time", 70), ("state", "State", 160))

INDENT = "    "


def table(found, mode):
    """[(iid, values)] for the tab. In an indented BOM the part number is pushed right by its level."""
    rows = []
    for number, line in enumerate(found):
        part = (INDENT * (line.level - 1) if mode == bom.INDENTED and line.level else "") + line.pn.short
        lead = line.field(purchasing_info.LEAD_TIME_DAYS)
        state = line.state_text + (" (loops back)" if line.loop else "")
        rows.append((f"line{number}", (part, line.revision, line.name, line.field(purchasing_info.SUPPLIER),
                                       line.field(purchasing_info.UNIT_COST), f"{lead} days" if lead else "",
                                       state)))
    return rows


def note(found, is_assembly, outdated=False):
    """The line above the table."""
    if not is_assembly:
        return "This revision uses no other parts, so it has no BOM."
    count = len(found)
    said = [f"{count} line{'s' if count != 1 else ''}"]
    said += bom.problems(found)
    if outdated:
        said.append("its list of parts used is out of date (References... then Update references)")
    return ". ".join(s[0].upper() + s[1:] for s in said) + ". No quantities: Litterbox records which parts an " \
                                                           "assembly uses, not how many."


def exported_text(path, count):
    return f"Exported a BOM of {count} line{'s' if count != 1 else ''} to {path}."
