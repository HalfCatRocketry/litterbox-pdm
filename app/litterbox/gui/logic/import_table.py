"""
import_table.py - the Import window's table: one row per item with its proposed part number, edits typed
into cells, and the texts around the import (summary, conflicts, result).
"""

from dataclasses import dataclass
from pathlib import Path

from litterbox.core import part_number
from litterbox.errors import LitterboxError
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import number_input
from litterbox.importing import import_numbering


IMPORT_KIND_LABELS = {"part": "Part", "assembly": "Assembly", "drawing": "Drawing only"}


IMPORT_TAGS = ("conflict", "off", "typed", "warn", "ok")      # strongest first


EDITABLE_COLUMNS = ("pn", "name", "description")


@dataclass
class ImportRow:
    item_id: int
    ticked: bool
    pn: str
    name: str
    description: str
    kind: str
    files: str
    notes: str
    tag: str            # how the row is coloured: see IMPORT_TAGS
    detail: str         # everything worth saying about the row, shown under the table when it is selected


def import_rows(candidates, proposal, conflicts=(), duplicates=None):
    """One ImportRow per item that could be imported, in order. `conflicts` come from import_numbering.Refresh/PNConflict.

    Rows that are selected show their new part number; unticked rows show none and are greyed.
    """
    placed = {id(entry.item): (index, entry) for index, entry in enumerate(proposal.entries)}
    problems = {c.index: c for c in conflicts}
    duplicates = duplicates or {}
    rows = []
    for item in candidates:
        files = ", ".join(sorted({f.type for f in item.files if f.type}))
        kind = IMPORT_KIND_LABELS.get(item.kind, item.kind)
        details = []
        if id(item) in placed:
            index, entry = placed[id(item)]
            conflict = problems.get(index)
            if conflict:
                tag, notes = "conflict", "Number taken: change it"
                details.append(conflict.reason)
            elif entry.manual:
                tag, notes = "typed", ""
            else:
                tag, notes = "ok", ""
            if duplicates.get(index):
                details = duplicates[index] + details
                if not conflict:
                    notes = "Possible duplicate"
                    tag = "warn"
            pn, name, description, ticked = str(entry.pn), entry.name, entry.description, True
        else:
            pn, name, description, ticked, tag, notes = "", item.name, item.description, False, "off", ""
        details += item.warnings
        if item.already_imported_as:
            details.append(f"Already imported as {item.already_imported_as}.")
        if item.identical_to:
            details.append("Identical file in item(s): " + ", ".join(str(i) for i in item.identical_to) + ".")
        details.append("Files: " + "; ".join(f.path for f in item.files))
        if not notes and (item.warnings or item.already_imported_as):
            first = item.warnings[0] if item.warnings else f"Already imported as {item.already_imported_as}"
            extra = len(item.warnings) - 1
            notes = first if len(first) <= 60 else first[:57] + "..."
            notes += f" (+{extra} more)" if extra > 0 else ""
            if tag in ("ok",):
                tag = "warn"
        rows.append(ImportRow(item.id, ticked, pn, name, description, kind, files, notes, tag, "\n".join(details)))
    return rows


def edit_import_cell(prepared, item_id, column, text):
    """Apply an edit made in the table. Returns '' if it worked, else a message to show the user."""
    from litterbox.parts import create
    from litterbox.importing import import_errors
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    if item is None or column not in EDITABLE_COLUMNS:
        return "That cell can't be edited."
    entries = prepared.proposal.entries
    index = next((n for n, e in enumerate(entries) if e.item is item), None)
    text = " ".join(str(text).split()) if column != "pn" else str(text).strip()
    if column == "pn":
        if index is None:
            return "Select the row first: unselected rows are not given a part number."
        if not text:
            prepared.proposal.reset_pn(index)
            return ""
        try:
            prepared.proposal.set_pn(index, text)
        except import_errors.ImportFailed as e:
            return str(e)
        return ""
    if column == "name":
        if not text:
            return "A name is required."
        if len(text) > create.MAX_NAME:
            return f"Keep the name under {create.MAX_NAME} characters."
    elif len(text) > create.MAX_DESCRIPTION:
        return f"Keep the description under {create.MAX_DESCRIPTION} characters."
    if index is None:
        item.name, item.description = (text, item.description) if column == "name" else (item.name, text)
    elif column == "name":
        entries[index].name = text
    else:
        entries[index].description = text
    return ""


def import_summary_line(candidates, proposal, conflicts=()):
    """The line above the table."""
    ticked, total = len(proposal.entries), len(candidates)
    text = f"{ticked} of {total} items will be imported"
    if conflicts:
        text += f"   |   {len(conflicts)} part number(s) can't be used (shown in red)"
    return text


def import_conflict_text(conflicts, renumbered=()):
    """The message shown when Finish & Import is refused because typed part numbers are taken."""
    lines = ["These part numbers can't be used:", ""]
    lines += [f"  Row {c.index + 1}: {c.reason}" for c in conflicts]
    lines += ["", "Change the part number in the highlighted rows (or clear it to let Litterbox choose), "
              "then press Finish & Import again. Nothing was imported."]
    if renumbered:
        lines += ["", f"{len(renumbered)} automatic number(s) were also replaced because they had been taken."]
    return "\n".join(lines)


def import_result_text(result):
    count = len(result.pns)
    text = f"Imported {action_rules.parts_text(count)}: {min(result.pns)}" + (f" to {max(result.pns)}" if count > 1 else "") + "."
    text += f"\n{len(result.files)} CAD file(s) were copied into the vault. Your original files were not changed."
    if result.renumbered:
        text += f"\n{len(result.renumbered)} automatic part number(s) had been taken meanwhile and were replaced."
    if result.warnings:
        text += "\n\nNotes:\n" + "\n".join("  " + w for w in result.warnings[:8])
    return text


def edit_import_pn(prepared, item_id, base_text, variant_text, repo=None):
    """Apply a part number typed into the two boxes [base]-[variant]. Returns '' if it worked, else a message.

    Both boxes empty gives the row back to Litterbox. Only one box filled in: an empty variant means the
    lowest free variant of that part number in the item's range (as in New Part, or New Assembly for an assembly),
    an empty base keeps the row's current base.
    Typing the numbers the row already has changes nothing (the row stays automatic).
    """
    from litterbox.records import record_store
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    entries = prepared.proposal.entries
    index = next((n for n, e in enumerate(entries) if item is not None and e.item is item), None)
    if item is None:
        return "That cell can't be edited."
    if index is None:
        return "Select the row first: unselected rows are not given a part number."
    try:
        base = number_input.parse_typed_number(base_text, "part number", part_number.BASE_DIGITS)
        variant = number_input.parse_typed_number(variant_text, "variant number", part_number.VARIANT_DIGITS)
    except ValueError as e:
        return str(e)
    if base is None and variant is None:
        prepared.proposal.reset_pn(index)
        return ""
    entry, org = entries[index], prepared.proposal.org
    if base is None:
        base = entry.pn.base
    if variant is None:
        try:
            low, high = import_numbering.variant_ranges(repo)[import_numbering.kind_of(item)] if repo else (1, None)
            variant = record_store.next_free_variant(repo, base, org, low, high) if repo else 1
        except Exception:
            variant = 1
    chosen = part_number.PN(org, base, variant)
    if chosen == entry.pn:
        return ""
    try:
        prepared.proposal.set_pn(index, str(chosen))
    except LitterboxError as e:
        return str(e)
    return ""


def import_external_text(error):
    """The question asked when some files use files that are not part of the import."""
    shown = [f"  {Path(file).name}  uses  {ref}" for file, ref in error.references[:10]]
    more = len(error.references) - len(shown)
    lines = [f"{len(error.references)} file reference(s) point at files that are not being imported:", ""] + shown
    if more > 0:
        lines.append(f"  ...and {more} more")
    lines += ["", "If you continue, the imported copies will still depend on those original files. They will only "
              "open completely on computers that have them at those paths, and the vault will not be "
              "self-contained.", "",
              "Usually it is better to say No, select the missing items (or scan their folder as well) and import again.",
              "", "Import anyway?"]
    return "\n".join(lines)


def import_cots_confirm_text(count, duplicates, names):
    """The question asked before an Import COTS goes ahead. `duplicates` is {row: [warnings]}; names[row] is the row's name."""
    lines = [f"You are about to import {action_rules.parts_text(count)} and record every one as COTS (a purchased part).",
             "", "Only choose this for parts you bought and have NOT modified. Anything you changed or "
             "designed yourself should be imported with the normal Import."]
    if duplicates:
        lines += ["", "These look like parts the vault already has (this is only a warning):"]
        for row in sorted(duplicates)[:8]:
            lines.append(f"  Row {row + 1}, {names[row]}:")
            lines += [f"      {text}" for text in duplicates[row][:3]]
        if len(duplicates) > 8:
            lines.append(f"  ...and {len(duplicates) - 8} more")
    lines += ["", "Import them as COTS?"]
    return "\n".join(lines)


def already_imported_question(items, total):
    """The warning after a scan finds files the vault remembers importing before (items with
    already_imported_as), out of `total` items: import them again, or cancel."""
    count = len(items)
    some = "All" if count == total else f"{count} of the {total}"
    lines = [f"{some} parts found may already have been imported into this vault:", ""]
    for item in items[:8]:
        lines.append(f"  {Path(item.main_path).name}  (imported as {item.already_imported_as})")
    if count > 8:
        lines.append(f"  ...and {count - 8} more")
    lines += ["", "If you go on, they are imported again as new parts with new part numbers. You can still untick "
                  "any of them in the table.", "", "Press OK to go on, or Cancel to stop without importing anything."]
    return "\n".join(lines)


NO_PROJECT = "No project"


def project_choices(projects):
    """{label: project name or None} for the Import window's Project box: no project first, then each project with
    its block ('Rover (120000 to 129999)')."""
    choices = {NO_PROJECT: None}
    choices.update({project.describe(): project.name for project in projects})
    return choices
