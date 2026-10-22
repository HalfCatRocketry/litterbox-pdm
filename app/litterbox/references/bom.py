"""
bom.py - an assembly's bill of materials, worked out from the parts each revision uses (the record's
`references`) and how many of each (its `quantities`, counted at check-in), plus the lines added to it by hand
(`bom_items`, with their own quantities: a non-CAD part, or anything in a non-CAD kit), so nothing is saved.

Three ways to list it:
    SINGLE     what the assembly itself uses
    INDENTED   the same, with what each sub-assembly uses under it, and so on down (level 1, 2, ...)
    FLAT       every part revision anywhere in the tree, once (a buying list)

Each line has `quantity`, how many its parent uses, and `total`, how many the whole assembly needs (the
quantities multiplied down the tree; in FLAT, added up over every place the part is used). Either is None when
an assembly on the way down has no counts (counted without SolidWorks, or before Litterbox counted parts).

Costs: a line's cost is its unit cost (purchasing info) times `total`. cost_summary() adds them up over every part
revision in the tree once (the FLAT list), whichever way the BOM is shown, so a sub-assembly's parts are always in it.
A sub-assembly with a unit cost of its own is counted as well as its parts.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from litterbox.core import revision_letters
from litterbox.records import purchasing_info
from litterbox.records import record_materials
from litterbox.references import reference_model

SINGLE, INDENTED, FLAT = "single", "indented", "flat"
MODES = (SINGLE, INDENTED, FLAT)
MODE_LABEL = {SINGLE: "Single level", INDENTED: "Indented", FLAT: "Every part once"}
MAX_LEVELS = 50                     # deeper than any real tree: a guard, alongside the loop check


@dataclass
class BomLine:
    level: int                      # 1 for what the assembly uses directly; 0 in a FLAT list
    pn: object                      # PN
    revision: str
    name: str = ""
    description: str = ""
    status: str = ""                # the part's record status (in_work, released, void), "" if it has no record
    state: str = reference_model.OK # how this use stands (reference_model: OK, STALE, ...)
    latest_released: str = ""
    cots: bool = False
    purchasing: dict = None         # the part's purchasing section (records/purchasing_info.py)
    sub_assembly: bool = False      # this revision uses other parts (in INDENTED they follow at level + 1)
    loop: bool = False              # it uses an assembly above it, so the tree stops here
    quantity: int = None            # how many its parent uses (None: not counted)
    total: int = None               # how many the whole assembly needs (None: not known)
    added: bool = False             # added to the BOM by hand, not read from the model
    material: str = ""              # that revision's material (records/record_materials.py), "" for none or not read

    @property
    def state_text(self):
        text = reference_model.STATE_TEXT[self.state]
        if self.state == reference_model.STALE:
            text += f" (Rev {self.latest_released})"
        return text

    def field(self, key):
        return purchasing_info.shown(self.purchasing, key)


def _line(records, stem, level):
    parts = reference_model.split_stem(stem)
    if parts is None:
        return None
    pn, revision = parts
    record = records.get(pn)
    state, latest = reference_model.classify(record, revision)
    if record is None:
        return BomLine(level, pn, revision, state=state)
    return BomLine(level, pn, revision, record.name, record.description, record.status, state, latest, record.cots,
                   dict(record.purchasing), bool(reference_model.stems_of(record, revision)),
                   material=record_materials.material(record, revision))


def quantities_of(record, revision):
    """{stem: count} for one revision of an assembly, or None if its parts were never counted."""
    return None if record is None else record.quantities.get(revision)


def _children(records, pn, revision, level, parent_total=1):
    record = records.get(pn)
    counts = quantities_of(record, revision)
    found = []
    for stem in reference_model.stems_of(record, revision):
        line = _line(records, stem, level)
        if line is None:
            continue
        line.added = reference_model.is_added(record, revision, stem)
        if line.added:
            line.quantity = record.bom_items[revision][stem]
        else:
            line.quantity = None if counts is None else counts.get(stem)
        line.total = None if line.quantity is None or parent_total is None else line.quantity * parent_total
        found.append(line)
    return sorted(found, key=lambda line: (str(line.pn), revision_letters.revision_number(line.revision)))


def _add(a, b):
    return None if a is None or b is None else a + b


def lines(records, pn, revision, mode=INDENTED):
    """The BOM of one revision of an assembly, as a list of BomLine. `records` is {PN: Record} (or a
    reference_model.LazyRecords). A part that isn't an assembly gives []."""
    if mode not in MODES:
        raise ValueError(f"unknown BOM mode {mode!r}")
    if mode == SINGLE:
        return _children(records, pn, revision, 1)
    found = []

    def walk(parent, parent_rev, level, above, parent_total):
        for line in _children(records, parent, parent_rev, level, parent_total):
            key = (line.pn, line.revision)
            line.loop = key in above or level >= MAX_LEVELS
            found.append(line)
            if line.sub_assembly and not line.loop:
                walk(line.pn, line.revision, level + 1, above | {key}, line.total)

    walk(pn, revision, 1, {(pn, revision)}, 1)
    if mode == INDENTED:
        return found
    once = {}                                   # FLAT: each part revision once, its totals added up
    for line in found:
        key = (line.pn, line.revision)
        if key in once:
            once[key].total = _add(once[key].total, line.total)
            once[key].loop = once[key].loop or line.loop
        else:
            line.level = 0
            once[key] = line
    for line in once.values():
        line.quantity = line.total
    return sorted(once.values(), key=lambda line: (str(line.pn), revision_letters.revision_number(line.revision)))


@dataclass
class CostSummary:
    total: Decimal = Decimal(0)     # unit cost x total quantity, added up over the part revisions that have both
    priced: int = 0                 # part revisions in `total`
    no_cost: int = 0                # parts (not assemblies) with no unit cost
    no_quantity: int = 0            # part revisions with a unit cost but no count


def unit_cost(line):
    """A line's unit cost as a Decimal, or None if it has none."""
    text = line.field(purchasing_info.UNIT_COST)
    try:
        return Decimal(text) if text else None
    except InvalidOperation:
        return None


def line_cost(line):
    """Unit cost x total quantity, or None when either is missing."""
    cost = unit_cost(line)
    return None if cost is None or line.total is None else cost * line.total


def cost_summary(records, pn, revision):
    """What one revision of an assembly costs, from every part revision in its tree once."""
    summary = CostSummary()
    for line in lines(records, pn, revision, FLAT):
        cost = unit_cost(line)
        if cost is None:
            summary.no_cost += 0 if line.sub_assembly else 1        # an assembly made in house has no price itself
        elif line.total is None:
            summary.no_quantity += 1
        else:
            summary.total += cost * line.total
            summary.priced += 1
    return summary


def problems(found):
    """Sentences about lines that need a look before the BOM is used (empty if none)."""
    counts = {}
    for line in found:
        if line.state != reference_model.OK:
            counts[line.state] = counts.get(line.state, 0) + 1
    said = [f"{count} line{'s' if count != 1 else ''}: {reference_model.STATE_TEXT[state].lower()}"
            for state, count in sorted(counts.items())]
    unknown = sum(1 for line in found if line.quantity is None)
    if unknown:
        said.append(f"{unknown} line{'s' if unknown != 1 else ''}: quantity not known")
    if any(line.loop for line in found):
        said.append("an assembly uses one of the assemblies it is in, so the tree stops there")
    return said
