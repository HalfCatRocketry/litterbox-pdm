"""
import_numbering.py - the part numbers an import proposes.

It proposes numbers DEFAULT_GAP plus up to DEFAULT_JITTER past the lowest free part number, looping round past the
highest the digits allow. Items can be put in one family (one base, several variants). Numbers are checked again
at the end, and any that someone took meanwhile are swapped for the next free ones.

Variants follow New Part and New Assembly (parts/create.py: variant_range): an assembly (.SLDASM) gets the first
variant of the assembly range (500 unless the org chose another), everything else 001; in a family, assemblies take
the free variants from 500 up and parts the free ones below. A typed number is never changed.
"""

import random
from dataclasses import dataclass, field

from litterbox.core import numbering
from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.core.part_number import PN
from litterbox.importing import import_errors
from litterbox.parts import create
from litterbox.parts import create_batch
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config


DEFAULT_GAP = 100           # propose numbers this far past the lowest free part number


DEFAULT_JITTER = 100        # plus up to this many more at random


@dataclass
class Entry:
    """One row of the import table."""
    item: object                    # the manifest Item
    pn: PN
    name: str
    description: str = ""
    manual: bool = False            # True once the user typed this part number


@dataclass
class Conflict:
    index: int                      # row in the table (0-based)
    pn: PN
    reason: str
    manual: bool                    # True: the user typed it, so the user has to change it


@dataclass
class Refresh:
    renumbered: list = field(default_factory=list)      # (row, old PN, new PN) for automatic numbers that were taken
    conflicts: list = field(default_factory=list)       # Conflicts left, which are always typed-in numbers


@dataclass
class Proposal:
    """The import table: one Entry per item, in order. The GUI edits these and shows `conflicts` in red."""
    entries: list
    org: str = ""
    note: str = ""                  # where the proposed numbers start and why, for the window's status line
    family: object = None           # a base number: every automatic row is a variant of it (None: separate numbers)

    def set_pn(self, index, text):
        """The user typed a part number into row `index`. Raises ImportFailed if it isn't a valid one."""
        try:
            new = part_number.parse(str(text).strip())
            part_number.check_new_base(new.base)
            part_number.check_variant(new.variant)
        except part_number.PNError as e:
            raise import_errors.ImportFailed(f"Row {index + 1}: {e}") from None
        entry = self.entries[index]
        entry.pn, entry.manual = new, True

    def reset_pn(self, index):
        """Hand the row back to Litterbox: it gets an automatic number again at the next refresh."""
        self.entries[index].manual = False

    def pns(self):
        return [e.pn for e in self.entries]


def kind_of(item):
    """create.ASSEMBLY for an assembly item (its main file is a .SLDASM), else create.PART."""
    return create.ASSEMBLY if getattr(item, "kind", "") == "assembly" else create.PART


def variant_ranges(repo):
    """{kind: (lowest, highest)} variant each kind of item takes on its own."""
    return {kind: create.variant_range(repo, kind) for kind in (create.PART, create.ASSEMBLY)}


def with_variant(repo, item, pn, ranges=None):
    """`pn` with the first variant of the item's range (pick_block's numbers are all variant 001)."""
    ranges = ranges or variant_ranges(repo)
    return PN(pn.org, pn.base, ranges[kind_of(item)][0])


def used_numbers(repo, org):
    existing = record_store.list_pns(repo, org)
    return set(existing), {pn.base for pn in existing}


def pick_block(repo, count, org, gap=DEFAULT_GAP, jitter=DEFAULT_JITTER, rng=None):
    """`count` part numbers (variant 001; with_variant gives an assembly its own) to propose: the free ones starting `gap` places (plus a random extra of up
    to `jitter`) past the LOWEST free part number, which is not the same as above the highest one in use. Numbers
    count up from the vault's start number and, past the highest the digits allow, round again from 1."""
    _taken, bases = used_numbers(repo, org)
    start = config.get_start_number(repo)
    allowed = project_rules.outside_blocks(config.get_projects(repo))      # automatic numbers stay out of project blocks
    lowest = numbering.free_bases(bases, 1, start, allowed)
    if not lowest:
        raise import_errors.ImportFailed(f"The vault does not have {count} free part numbers left.")
    extra = (rng or random).randrange(jitter) if jitter > 0 and gap > 0 else 0
    first = numbering.base_after(lowest[0], max(gap, 0) + extra, start)
    free = numbering.free_bases(bases, count, first, allowed)
    if len(free) < count:
        raise import_errors.ImportFailed(f"The vault does not have {count} free part numbers left.")
    return [PN(org, b, 1) for b in free]


def family_free_variants(repo, proposal, skip=(), kind=None):
    """The variant numbers of the family base that nothing is using: not in the vault, and not typed into a row.
    With `kind`, only those in its range (parts below the assembly start, assemblies from it)."""
    base, org = proposal.family, proposal.org
    used = {pn.variant for pn in record_store.list_pns(repo, org) if pn.base == base}
    used |= {e.pn.variant for i, e in enumerate(proposal.entries)
             if e.manual and e.pn.base == base and i not in skip}
    low, high = variant_ranges(repo)[kind] if kind else (part_number.MIN_VARIANT, part_number.MAX_VARIANT)
    return [v for v in range(low, high + 1) if v not in used]


def family_shortage(base, wanted, free, kind=None, ranges=None):
    if kind is None:
        return (f"Part number {part_number.format_base(base)} only has {free} unused variant number(s) "
                f"(the most a part number can have is {part_number.MAX_VARIANT}), but {wanted} part(s) are being "
                f"imported to it. Choose another number, or import fewer parts at a time.")
    low, high = ranges[kind]
    plural = {create.PART: "parts", create.ASSEMBLY: "assemblies"}[kind]
    return (f"Part number {part_number.format_base(base)} only has {free} unused variant number(s) for {plural} "
            f"({part_number.format_variant(low)} to {part_number.format_variant(high)}), but {wanted} {plural} are "
            "being imported to it. Choose another number, or import fewer at a time.")


def _family_variants(repo, proposal, entries, skip=(), keep=()):
    """{entry index in `entries`: variant} giving each entry a free variant of the family base in its own range.
    Raises FamilyFull (changing nothing) if a range runs short. `keep` are variants that stay as they are."""
    ranges = variant_ranges(repo)
    chosen = {}
    for kind in (create.PART, create.ASSEMBLY):
        wanted = [n for n, e in enumerate(entries) if kind_of(e.item) == kind]
        if not wanted:
            continue
        free = [v for v in family_free_variants(repo, proposal, skip, kind) if v not in keep]
        if len(free) < len(wanted):
            raise import_errors.FamilyFull(family_shortage(proposal.family, len(wanted), len(free), kind, ranges))
        chosen.update(zip(wanted, free))
    return chosen


def set_family(repo, proposal, base, sync=True):
    """Import every automatic row as a variant of one base number (`base`), or back to separate numbers (None).

    If the base is already in use the new variants start from the lowest unused ones. Raises ImportFailed, leaving
    the table as it was, if the base is not valid or does not have enough unused variants for the rows."""
    if base is None:
        count = sum(1 for e in proposal.entries if not e.manual)
        if proposal.family is None:
            return
        if sync:
            try:
                create_batch.sync_latest(repo)
            except create.CreateError as e:
                raise import_errors.ImportFailed(str(e)) from None
        proposal.family = None
        if count:
            ranges = variant_ranges(repo)
            for entry, pn in zip((e for e in proposal.entries if not e.manual), pick_block(repo, count, proposal.org)):
                entry.pn = with_variant(repo, entry.item, pn, ranges)
        return
    try:
        base = part_number.check_new_base(base)
    except part_number.PNError as e:
        raise import_errors.ImportFailed(str(e)) from None
    if sync:
        try:
            create_batch.sync_latest(repo)
        except create.CreateError as e:
            raise import_errors.ImportFailed(str(e)) from None
    previous = proposal.family
    proposal.family = base
    automatic = [e for e in proposal.entries if not e.manual]
    try:
        chosen = _family_variants(repo, proposal, automatic)
    except import_errors.FamilyFull:
        proposal.family = previous
        raise
    for n, entry in enumerate(automatic):
        entry.pn = PN(proposal.org, base, chosen[n])


def check_proposal(repo, proposal):
    """Conflicts in the table right now (reads the local copy; call sync first for the latest).

    An automatic row with separate numbers needs a part number nobody else has, whatever its variant: an assembly's
    HCR-00003-500 must not land on the base of someone's HCR-00003-001. Typed rows and a family only need their
    own variant."""
    org = proposal.org
    taken, bases = used_numbers(repo, org)
    claimed, claimed_bases, conflicts = {}, {}, []
    order = [i for i, e in enumerate(proposal.entries) if e.manual] + \
            [i for i, e in enumerate(proposal.entries) if not e.manual]
    for index in order:
        entry = proposal.entries[index]
        separate = not entry.manual and proposal.family is None
        if entry.pn.org != org:
            reason = f"{entry.pn} is for a different organization (this vault uses {org})."
        elif entry.pn in taken:
            try:
                holder = record_store.load(repo, entry.pn)
                reason = f"{entry.pn} is already used by '{holder.name}'."
            except record_model.RegistryError:
                reason = f"{entry.pn} is already used."
        elif entry.pn in claimed:
            reason = f"{entry.pn} is used twice in this import (rows {claimed[entry.pn] + 1} and {index + 1})."
        elif separate and entry.pn.base in bases:
            reason = f"Part number {part_number.format_base(entry.pn.base)} is already used in the vault."
        elif separate and entry.pn.base in claimed_bases:
            reason = (f"Part number {part_number.format_base(entry.pn.base)} is already used in this import "
                      f"(row {claimed_bases[entry.pn.base] + 1}).")
        else:
            claimed[entry.pn] = index
            claimed_bases.setdefault(entry.pn.base, index)
            continue
        conflicts.append(Conflict(index, entry.pn, reason, entry.manual))
    return sorted(conflicts, key=lambda c: c.index)


def _renumber_automatic(repo, proposal, conflicts):
    """Give every automatic row that conflicts a new, free number near the rest of the proposed block. Returns the changes."""
    if proposal.family is not None:
        return _renumber_family(repo, proposal, conflicts)
    taken, bases = used_numbers(repo, proposal.org)
    in_use = {e.pn.base for i, e in enumerate(proposal.entries) if i not in {c.index for c in conflicts if not c.manual}}
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    bad = [c for c in conflicts if not c.manual]
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    near = min(automatic, default=config.get_start_number(repo))          # stay near the proposed block
    free = numbering.free_bases(bases | in_use, len(bad), near, project_rules.outside_blocks(config.get_projects(repo)))
    if len(free) < len(bad):
        raise import_errors.ImportFailed("The vault has run out of part numbers for this import.")
    changes, ranges = [], variant_ranges(repo)
    for conflict, candidate in zip(bad, free):
        entry = proposal.entries[conflict.index]
        new = with_variant(repo, entry.item, PN(proposal.org, candidate, 1), ranges)
        changes.append((conflict.index, entry.pn, new))
        entry.pn = new
    return changes


def _renumber_family(repo, proposal, conflicts):
    """Family mode: an automatic row whose variant was taken gets the next unused variant of the base."""
    bad = sorted({c.index for c in conflicts if not c.manual})
    keep = {e.pn.variant for i, e in enumerate(proposal.entries)
            if i not in bad and e.pn.base == proposal.family}
    chosen = _family_variants(repo, proposal, [proposal.entries[i] for i in bad], skip=set(bad), keep=keep)
    changes = []
    for n, index in enumerate(bad):
        entry = proposal.entries[index]
        new = PN(proposal.org, proposal.family, chosen[n])
        changes.append((index, entry.pn, new))
        entry.pn = new
    return changes


def refresh(repo, proposal, log=print):
    """Download the newest records, replace automatic numbers that are now taken, and report what is left.

    Typed-in numbers are never changed: if they are taken they are returned in `conflicts`
    (the table shows those rows in red) and the user decides what to do.
    """
    try:
        create_batch.sync_latest(repo)
    except create.CreateError as e:
        raise import_errors.ImportFailed(str(e)) from None
    renumbered = []
    for _round in range(5):
        conflicts = check_proposal(repo, proposal)
        automatic = [c for c in conflicts if not c.manual]
        if not automatic:
            break
        renumbered += _renumber_automatic(repo, proposal, conflicts)
    for row, old, new in renumbered:
        log(f"Row {row + 1}: {old} was taken, so it now gets {new}.")
    return Refresh(renumbered, [c for c in check_proposal(repo, proposal) if c.manual])
