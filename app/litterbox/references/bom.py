"""
bom.py - an assembly's bill of materials, worked out from the parts each revision uses (the record's
`references`), so it is never stale and nothing is saved.

Three ways to list it:
    SINGLE     what the assembly itself uses
    INDENTED   the same, with what each sub-assembly uses under it, and so on down (level 1, 2, ...)
    FLAT       every part revision anywhere in the tree, once (a buying list)

References record WHICH part revisions an assembly uses, not how many of each, so a BOM has no quantities yet
(docs/REMINDERS.md, "BOM quantities").
"""

from dataclasses import dataclass

from litterbox.core import revision_letters
from litterbox.records import purchasing_info
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
                   dict(record.purchasing), bool(record.references.get(revision)))


def _children(records, pn, revision, level):
    record = records.get(pn)
    stems = record.references.get(revision, []) if record is not None else []
    found = [line for line in (_line(records, stem, level) for stem in stems) if line is not None]
    return sorted(found, key=lambda line: (str(line.pn), revision_letters.revision_number(line.revision)))


def lines(records, pn, revision, mode=INDENTED):
    """The BOM of one revision of an assembly, as a list of BomLine. `records` is {PN: Record} (or a
    reference_model.LazyRecords). A part that isn't an assembly gives []."""
    if mode not in MODES:
        raise ValueError(f"unknown BOM mode {mode!r}")
    if mode == SINGLE:
        return _children(records, pn, revision, 1)
    found, seen = [], set()

    def walk(parent, parent_rev, level, above):
        for line in _children(records, parent, parent_rev, level):
            key = (line.pn, line.revision)
            line.loop = key in above or level >= MAX_LEVELS
            if mode == FLAT:
                if key in seen:
                    continue                    # listed already, with everything under it
                seen.add(key)
                line.level = 0
                found.append(line)
            else:
                found.append(line)
            if line.sub_assembly and not line.loop:
                walk(line.pn, line.revision, level + 1, above | {key})

    walk(pn, revision, 1, {(pn, revision)})
    if mode == FLAT:
        found.sort(key=lambda line: (str(line.pn), revision_letters.revision_number(line.revision)))
    return found


def problems(found):
    """Sentences about lines that need a look before the BOM is used (empty if none)."""
    counts = {}
    for line in found:
        if line.state != reference_model.OK:
            counts[line.state] = counts.get(line.state, 0) + 1
    said = [f"{count} line{'s' if count != 1 else ''}: {reference_model.STATE_TEXT[state].lower()}"
            for state, count in sorted(counts.items())]
    if any(line.loop for line in found):
        said.append("an assembly uses one of the assemblies it is in, so the tree stops there")
    return said
