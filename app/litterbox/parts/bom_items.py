"""
bom_items.py - BOM lines added by hand: parts an assembly's BOM lists that its model doesn't (the record's
`bom_items`, per revision, with a quantity each).

- A CAD assembly (one with a .SLDASM) takes only non-CAD parts this way: paint, glue, raw stock. Its CAD parts
  come from the model, so adding one by hand could count it twice.
- A non-CAD assembly (a kit, made with New Assembly as non-CAD) has no model, so its BOM is only these lines, and
  it takes any part, CAD or not.

You must have the assembly checked out, and the change goes up with your next Save Progress or Check In, like Edit
Details. A line names the part revision it uses: the part's latest released revision, or its working one if it was
never released, as a model's references do.
"""

from litterbox.cad import file_types
from litterbox.core.filenames import file_stem
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.vault import config


MAX_QUANTITY = 1_000_000


def is_kit(repo, record):
    """A non-CAD assembly: non-CAD, with a variant in the assembly range (New Assembly)."""
    return record.kind == record_model.KIND_NONCAD and record.pn.variant >= config.get_assembly_variant_start(repo)


def takes_items(repo, record, files):
    """True if this part's BOM can have lines added by hand: a CAD assembly (its working revision has a .SLDASM,
    `files`) or a non-CAD assembly."""
    if record.kind == record_model.KIND_NONCAD:
        return is_kit(repo, record)
    return any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS for f in files)


def item_problem(assembly, item):
    """Why `item` (a Record) can't be added by hand to `assembly`'s BOM ("" if it can)."""
    if item.pn == assembly.pn:
        return "An assembly can't list itself."
    if item.status == record_model.STATUS_VOID:
        return f"{item.pn} is void."
    if assembly.kind == record_model.KIND_CAD and item.kind != record_model.KIND_NONCAD:
        return (f"{item.pn} is a CAD part. Only non-CAD parts can be added by hand to a CAD assembly's BOM: its CAD "
                "parts come from the model.")
    return ""


def item_stem(item):
    """The part revision a new line uses: 'HCR-00009-001_A' (latest released, or working if never released)."""
    return file_stem(item.pn, item.released_revision or item.revision)


def clean_quantity(quantity):
    try:
        number = int(str(quantity).strip())
    except (TypeError, ValueError):
        raise LitterboxError("The quantity must be a whole number.") from None
    if not 1 <= number <= MAX_QUANTITY:
        raise LitterboxError(f"The quantity must be from 1 to {MAX_QUANTITY:,}.")
    return number


def _checked_out_assembly(repo, pn, user):
    permission_check.check_permission(repo, user, "edit_details")
    if not lfs_locks.is_mine(lfs_locks.get_locks(repo, strict=True), record_store.record_relpath(pn)):
        raise LitterboxError(f"You don't have {pn} checked out. Check it out to change its BOM.")
    record = record_store.load(repo, pn)
    if not takes_items(repo, record, record_files.cad_files(repo, pn, record.revision)):
        raise LitterboxError(f"{pn} isn't an assembly, so it has no BOM to add to.")
    return record


@converts_errors
def set_item(repo, pn, item_pn, quantity):
    """Add a line to the working revision's BOM, or change its quantity. Returns the stem it uses."""
    repository.validate_repo(repo)
    pn, item_pn = batch_core.as_pn(pn), batch_core.as_pn(item_pn)
    user = repository.get_user(repo)
    record = _checked_out_assembly(repo, pn, user)
    item = record_store.load(repo, item_pn)
    problem = item_problem(record, item)
    if problem:
        raise LitterboxError(problem)
    quantity = clean_quantity(quantity)
    stem = next((s for s in record.bom_items.get(record.revision, {}) if s.rsplit("_", 1)[0] == str(item_pn)),
                item_stem(item))
    record_lifecycle.set_bom_item(record, user, stem, quantity)
    record_store.save(repo, record)
    return stem


@converts_errors
def remove_item(repo, pn, stem):
    """Take a line added by hand off the working revision's BOM."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    user = repository.get_user(repo)
    record = _checked_out_assembly(repo, pn, user)
    if stem not in record.bom_items.get(record.revision, {}):
        raise LitterboxError(f"{stem} isn't a line added by hand to Rev {record.revision}.")
    record_lifecycle.set_bom_item(record, user, stem, None)
    record_store.save(repo, record)
