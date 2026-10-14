"""
number_suggestions.py - what the New Part dialog shows: the suggested part and variant numbers, whether
a typed number is free, and the variants a base already has. Reads the local copy only; nothing is reserved.
"""

from dataclasses import dataclass

from litterbox.core.part_number import PN, check_base, check_new_base, check_variant
from litterbox.git import repository
from litterbox.parts import create
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config


# These two read your local copy only (no network). They are for showing a
# suggestion in a dialog; the real choice is always made again when you create.
@create.friendly
def suggest_part_number(repo, org=None):
    """The part number New Part would use right now if the box were left empty."""
    repository.validate_repo(repo)
    return record_store.next_free_base(repo, create.resolve_org(repo, org), config.get_start_number(repo))


@create.friendly
def suggest_numbers(repo, base=None, org=None):
    """What New Part would use if the boxes were left empty: (part number, variant number).

    `base` is the part number typed so far, if any. The variant is 1 unless that
    part number is already in use, in which case it is the lowest unused variant.
    """
    repository.validate_repo(repo)
    org = create.resolve_org(repo, org)
    number = check_base(base) if base is not None else record_store.next_free_base(
        repo, org, config.get_start_number(repo))
    return number, record_store.next_free_variant(repo, number, org)


@dataclass
class NumberCheck:
    pn: PN                  # the part number that would be created
    taken: bool = False     # True if a record with this part number already exists
    name: str = ""          # the name of the part that has it
    status: str = ""        # its status (in_work, released, void)


@create.friendly
def check_numbers(repo, base=None, variant=None, org=None):
    """What New Part would create for these boxes, and whether that part number is free.

    Leave `base` or `variant` as None for a box left empty (the suggested number is used).
    Reads your local copy only. New Part does the same check again for real, so
    this is only for telling the user early.
    """
    repository.validate_repo(repo)
    org = create.resolve_org(repo, org)
    number = check_new_base(base) if base is not None else check_new_base(
        record_store.next_free_base(repo, org, config.get_start_number(repo)))
    chosen = check_variant(variant) if variant is not None else record_store.next_free_variant(repo, number, org)
    pn = PN(org, number, chosen)
    if not record_store.exists(repo, pn):
        return NumberCheck(pn)
    try:
        record = record_store.load(repo, pn)
    except record_model.RegistryError:
        return NumberCheck(pn, True, "(its record can't be read)", "")
    return NumberCheck(pn, True, record.name, record.status)


@create.friendly
def suggest_variant_number(repo, base, org=None):
    """The variant number New Part would use right now for this part number."""
    repository.validate_repo(repo)
    return record_store.next_free_variant(repo, check_base(base), create.resolve_org(repo, org))


@create.friendly
def list_variants(repo, base, org=None):
    """The records of every variant of a part number, in order (for showing what already exists)."""
    repository.validate_repo(repo)
    return record_store.load_variants(repo, check_base(base), create.resolve_org(repo, org))
