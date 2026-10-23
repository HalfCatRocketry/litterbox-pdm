"""
import_prepare.py - phase 2 of an import: read the manifest, read every file's references through
SolidWorks, and propose part numbers. Nothing in the vault changes yet.
"""

import os
from dataclasses import dataclass

from litterbox.cad import file_types
from litterbox.cad.solidworks import sw_backend
from litterbox.core import part_number
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.importing import import_errors
from litterbox.importing import import_journal
from litterbox.importing import import_numbering
from litterbox.importing import import_paths
from litterbox.importing import import_plan
from litterbox.importing import manifest as manifest_module
from litterbox.parts import create
from litterbox.parts import create_batch
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.vault import config


@dataclass
class Prepared:
    manifest: object
    manifest_path: str
    candidates: list            # every manifest item that has no part number yet, included or not
    refs: dict
    proposal: import_numbering.Proposal
    backend: object
    owns_backend: bool
    version: str = ""
    allow_external: bool = False
    cots: bool = False          # Import COTS: every part in this import is recorded as purchased

    @property
    def items(self):
        """The items that will be imported: the ones in the table."""
        return [e.item for e in self.proposal.entries]

    def close(self):
        if self.owns_backend:
            self.backend.close()


def free_pn(repo, proposal, item=None):
    """An unused part number for a row added to the table (for `item`): just after the automatic ones already there,
    with the first variant of the item's range (an assembly's start from 500)."""
    kind = import_numbering.kind_of(item)
    if proposal.family is not None:
        used = {e.pn.variant for e in proposal.entries if e.pn.base == proposal.family}
        free = [v for v in import_numbering.family_free_variants(repo, proposal, kind=kind) if v not in used]
        if not free:
            raise import_errors.FamilyFull(import_numbering.family_shortage(
                proposal.family, 1, 0, kind, import_numbering.variant_ranges(repo)))
        return PN(proposal.org, proposal.family, free[0])
    _taken, bases = import_numbering.used_numbers(repo, proposal.org)
    here = {e.pn.base for e in proposal.entries}
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    if automatic or proposal.project is not None:      # just after the numbers already proposed
        free = import_numbering.free_for(repo, proposal, bases | here, 1, max(automatic) + 1 if automatic else None)
    else:
        free = [import_numbering.pick_block(repo, 1, proposal.org)[0].base]
    if not free:
        raise import_errors.ImportFailed("The vault has run out of part numbers for this import.")
    return import_numbering.with_variant(repo, item, PN(proposal.org, free[0], 1))


def set_included(repo, prepared, item_id, include):
    """Tick or untick one item (by its manifest id): adds or removes its row in the table."""
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    if item is None:
        raise import_errors.ImportFailed(f"There is no item {item_id} left to import.")
    entries = prepared.proposal.entries
    present = next((e for e in entries if e.item is item), None)
    if not include:
        if present:
            entries.remove(present)
        item.include = False
        return
    if present:
        return
    missing = [f.path for f in item.files if not os.path.isfile(f.path)]
    if missing:
        raise import_errors.ImportFailed(f"Can't include '{item.name}': {missing[0]} can't be found.")
    if import_paths.path_key(item.main_path) not in prepared.refs:
        raise import_errors.ImportFailed(f"Can't include '{item.name}': its references were not read.")
    position = prepared.candidates.index(item)
    before = sum(1 for e in entries if prepared.candidates.index(e.item) < position)
    entries.insert(before, import_numbering.Entry(item, free_pn(repo, prepared.proposal, item), item.name, item.description))
    item.include = True


def number_note(repo, proposal):
    """Where the proposed part numbers come from, for the window's status line."""
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    first = part_number.format_base(min(automatic)) if automatic else ""
    if proposal.project is not None:
        return (f"Importing into project {proposal.project.describe()}: the proposed part numbers are the lowest "
                "unused ones in it" + (f", from {first}." if first else "."))
    _taken, bases = import_numbering.used_numbers(repo, proposal.org)
    return ((f"Proposed part numbers start at {first}. " if first else "")
            + f"This vault's start number is {part_number.format_base(config.get_start_number(repo))}; the highest "
            "part number in use is " + (part_number.format_base(max(bases)) if bases else "(none yet)") + ". "
            + config.explain_start_number(repo))


def prepare(repo, manifest_path, backend=None, allow_external=False, cancel=None, progress=None,
            log=print, org=None, gap=import_numbering.DEFAULT_GAP, jitter=import_numbering.DEFAULT_JITTER, rng=None, cots=False,
            project=None):
    """Check the manifest, read every file's references, refresh the vault and propose part numbers. `project` is the
    name of the project to import into (None: none); its numbers come from the project's block.

    Writes nothing to the vault. Returns a Prepared with a `proposal` (the table to show).
    Call close() on it when done, whether or not the import went ahead.
    """
    repository.validate_repo(repo)
    if project:
        try:
            permission_check.check_new_number(repo, project)         # a restricted project: its members only
        except LitterboxError as e:
            raise import_errors.ImportFailed(str(e)) from None
    status = import_journal.recover(repo, log)
    if status != "nothing":
        log(f"(An earlier import was interrupted; it was dealt with: {status}.)")
    try:
        mf = manifest_module.load(manifest_path)
    except manifest_module.ManifestError as e:
        raise import_errors.ImportFailed(str(e)) from None
    found_problems = manifest_module.problems(mf)
    if found_problems:
        raise import_errors.ImportFailed("The manifest needs fixing first:\n" + "\n".join(found_problems[:10]))
    items = manifest_module.pending_items(mf)
    if not items:
        raise import_errors.ImportFailed("There is nothing left to import: every included item already has a part number.")
    missing = [p for item in items for p in import_plan.item_files(item) if not os.path.isfile(p)]
    if missing:
        raise import_errors.ImportFailed(f"{len(missing)} file(s) in the manifest can't be found:\n" + "\n".join(missing[:8]))
    # References are read for every item that could be ticked later, so ticking is instant.
    candidates = [i for i in mf.items if not i.pn]
    readable = [i for i in candidates if all(os.path.isfile(p) for p in import_plan.item_files(i))]
    for item in items:
        if import_paths.ext_of(item.main_path) not in file_types.SOLIDWORKS_EXTENSIONS:
            raise import_errors.ImportFailed(f"Item {item.id}: {item.main_path} is not a SolidWorks file.")

    owns_backend = backend is None
    backend = backend or sw_backend.SolidWorksBackend()
    try:
        version = backend.version()
        if version:
            log(f"SolidWorks version {version}. (Copies are not re-saved, but anyone opening them later "
                "needs a SolidWorks at least as new as the originals.)")
        refs = import_plan.read_references(readable, backend, progress, cancel)
        try:
            create_batch.sync_latest(repo)                               # the newest list of part numbers
            org = create.resolve_org(repo, org)
            chosen, _projects = create.chosen_project(repo, project)
            block = import_numbering.pick_block(repo, len(items), org, gap, jitter, rng, project=chosen)
            ranges = import_numbering.variant_ranges(repo)
        except (create.CreateError, config.ConfigError, record_model.RegistryError, part_number.PNError) as e:
            raise import_errors.ImportFailed(str(e)) from None
        proposal = import_numbering.Proposal([import_numbering.Entry(item, import_numbering.with_variant(repo, item, pn, ranges),
                                                                     item.name, item.description)
                                              for item, pn in zip(items, block)], org, project=chosen)
        proposal.note = number_note(repo, proposal)
        return Prepared(mf, str(manifest_path), candidates, refs, proposal, backend, owns_backend, version,
                        allow_external, cots)
    except BaseException:
        if owns_backend:
            backend.close()
        raise
