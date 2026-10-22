"""
material_text.py - parts' materials in words (records/record_materials.py, parts/part_materials.py): the Material
column, the Details tab's line, and the status line after Update Material.
"""

from litterbox.parts import part_materials
from litterbox.records import record_lifecycle
from litterbox.records import record_materials

NOT_READ = "Not read yet"


def column_text(row):
    """The Material column: the working revision's material, blank when none is assigned (or the part has no part
    file), 'Not read yet' when it has a part file whose material wasn't read."""
    if getattr(row, "material_outdated", False):
        return NOT_READ
    return getattr(row, "material", "") or ""


def details_text(record, rev, files):
    """The Details tab's Material line for a revision, or None when it has no part file (no line at all)."""
    if record_lifecycle.material_needs_update(record, rev, files):
        return f"{NOT_READ}: check it in with SolidWorks open, or use Part > Update Material"
    if not record_materials.is_read(record, rev):
        return None
    return record_materials.material(record, rev) or "None assigned in SolidWorks"


def summary(results):
    """(text, problems) for the status line after Update Material: results are part_materials.update_materials'."""
    updated = [pn for pn, outcome in results.items() if outcome in (part_materials.UPDATED, part_materials.LOCAL)]
    local = [pn for pn, outcome in results.items() if outcome == part_materials.LOCAL]
    same = [pn for pn, outcome in results.items() if outcome == part_materials.UNCHANGED]
    skipped = [(pn, outcome.removeprefix("skipped: ")) for pn, outcome in results.items()
               if outcome.startswith("skipped")]
    said = []
    if updated:
        said.append(f"Updated the material of {len(updated)} part{'s' if len(updated) != 1 else ''}"
                    + (" (yours go up with your next Check In)" if local else ""))
    if same:
        said.append(f"{len(same)} already up to date")
    if skipped:
        said.append(f"{len(skipped)} skipped")
    return ", ".join(said) or "Nothing to update", [f"{pn}: {why}" for pn, why in skipped]
