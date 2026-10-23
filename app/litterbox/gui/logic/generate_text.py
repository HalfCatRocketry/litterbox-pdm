"""
generate_text.py - the Generate STEP/PDF window's table and words: for each part, what will happen with the choices
made in the window (made in your checkout, made and uploaded now, saved to a folder, or skipped and why), and the
summary afterwards. The vault side's own rules are in parts/generate_files.py; this follows them from the parts list.
"""

from dataclasses import dataclass

from litterbox.exporting import step_pdf
from litterbox.parts import generate_files
from litterbox.records import record_exports

IN_VAULT, OUTSIDE = "vault", "outside"
WHERE_LABEL = {IN_VAULT: "Save in Litterbox (with the working revision)",
               OUTSIDE: "Save to a folder outside Litterbox"}


@dataclass
class TableRow:
    pn: object
    revision: str
    name: str
    what: str           # what will happen to it
    runs: bool          # False: skipped


def _kinds_text(kinds):
    return " and ".join(record_exports.LABEL[kind] for kind in record_exports.KINDS if kind in kinds)


def _missing_text(kinds):
    """Why a part can make none of the kinds asked for."""
    wanted = [kind for kind in record_exports.KINDS if kind in kinds]
    if len(wanted) == 2:
        return "No model or drawing"
    return "No model" if wanted == [record_exports.STEP] else "No drawing"


def _only_text(kinds, chosen):
    """' (STEP only: no drawing)' when a part can make only some of the kinds asked for."""
    left_out = [kind for kind in record_exports.KINDS if kind in kinds and kind not in chosen]
    if not left_out:
        return ""
    return f" ({_kinds_text(chosen)} only: no {'drawing' if left_out == [record_exports.PDF] else 'model'})"


def row_text(row, kinds, where, force=False):
    """(what will happen, runs) for one part of the parts list (a PartStatus)."""
    possible = step_pdf.possible_kinds(row.files)
    chosen = [kind for kind in record_exports.KINDS if kind in kinds and kind in possible]
    if not chosen:
        return f"{_missing_text(kinds)}: skipped", False
    made, only = _kinds_text(chosen), _only_text(kinds, chosen)
    if where == OUTSIDE:
        return f"{made} saved to the folder{only}", True
    if row.kind == "void":
        return "Void: skipped", False
    if row.kind == "pending":
        return "Waiting for sign-offs: skipped", False
    if row.kind == "theirs":
        return f"Checked out by {row.locked_by}: skipped", False
    if row.kind in ("unclaimed", "stray"):
        return "Has changes that are not checked in: skipped", False
    if row.kind == "mine":
        return f"{made} made in your checkout, uploaded at Check In{only}", True
    if row.kind == "released":
        existing_kinds = [kind for kind in possible if step_pdf.existing(kind, row.files)]
        if generate_files.up_to_date(list(row.files_needed), existing_kinds, possible):
            if not force:
                return "Released, up to date: skipped", False
            return f"{made} made again and uploaded now{only}", True
    return f"{made} made and uploaded now{only}", True


def table(rows, kinds, where, force=False):
    """A TableRow for each part (PartStatus rows), in the order given."""
    result = []
    for row in rows:
        what, runs = row_text(row, kinds, where, force)
        result.append(TableRow(row.pn, row.revision, row.name, what, runs))
    return result


def count_text(table_rows):
    runs = sum(1 for row in table_rows if row.runs)
    skipped = len(table_rows) - runs
    text = f"{runs} part{'s' if runs != 1 else ''}"
    return text + (f", {skipped} skipped" if skipped else "")


def done_text(result):
    """The status line after making files in the vault (a generate_files.Generated)."""
    made = sum(len(names) for _pn, names in result.done)
    text = f"Made {made} file{'s' if made != 1 else ''} for {len(result.done)} part{'s' if len(result.done) != 1 else ''}"
    return text + (f", {len(result.failed)} failed" if result.failed else "")


def boms_saved_text(boms):
    """The status line after BOMs were saved with a release: [(pn, vault path)]."""
    if len(boms) == 1:
        return f"Saved the BOM of {boms[0][0]} with its release ({boms[0][1].rsplit('/', 1)[-1]})"
    return f"Saved the BOMs of {len(boms)} assemblies with their release"


def saved_text(folder, made):
    """The status line after saving files to a folder outside Litterbox (a step_pdf.Made)."""
    count = sum(len(files) for files in made.made.values())
    text = f"Saved {count} file{'s' if count != 1 else ''} to {folder}"
    return text + (f", {len(made.errors)} failed" if made.errors else "")


def failure_lines(failed):
    """[(pn, why)] as lines for a message."""
    return "\n\n".join(f"{pn}: {why}" for pn, why in failed)
