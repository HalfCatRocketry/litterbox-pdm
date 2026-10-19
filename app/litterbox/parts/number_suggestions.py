"""
number_suggestions.py - what the New Part dialog shows: the suggested part and variant numbers, whether
a typed number is free, and the variants a base already has. Reads the local copy only; nothing is reserved.
`project` is the project chosen in the dialog (its name, or None): numbers then come from its block, and a typed
number in the wrong block is refused, as New Part itself does (create.py).
"""

from dataclasses import dataclass

from litterbox.core.part_number import PN, check_base, check_new_base, check_variant
from litterbox.git import repository
from litterbox.parts import create
from litterbox.records import record_model
from litterbox.records import record_store


# These two read your local copy only (no network). They are for showing a
# suggestion in a dialog; the real choice is always made again when you create.
@create.friendly
def suggest_part_number(repo, org=None, project=None):
    """The part number New Part would use right now if the box were left empty."""
    repository.validate_repo(repo)
    org = create.resolve_org(repo, org)
    return create.next_number(repo, org, *create.chosen_project(repo, project))


@create.friendly
def suggest_numbers(repo, base=None, org=None, project=None, kind=create.PART):
    """What New Part would use if the boxes were left empty: (part number, variant number).

    `base` is the part number typed so far, if any. The variant is the first of the kind's range (001 for a part,
    500 for an assembly) unless that part number already has it, in which case it is the lowest unused one there.
    """
    repository.validate_repo(repo)
    org = create.resolve_org(repo, org)
    number = check_base(base) if base is not None else create.next_number(
        repo, org, *create.chosen_project(repo, project))
    return number, create.next_variant_number(repo, number, org, kind)


@dataclass
class NumberCheck:
    pn: PN                  # the part number that would be created
    taken: bool = False     # True if a record with this part number already exists
    name: str = ""          # the name of the part that has it
    status: str = ""        # its status (in_work, released, void)


@create.friendly
def check_numbers(repo, base=None, variant=None, org=None, project=None, kind=create.PART):
    """What New Part would create for these boxes, and whether that part number is free.

    Leave `base` or `variant` as None for a box left empty (the suggested number is used).
    Reads your local copy only. New Part does the same check again for real, so
    this is only for telling the user early.
    """
    repository.validate_repo(repo)
    org = create.resolve_org(repo, org)
    project_chosen, projects = create.chosen_project(repo, project)
    if base is None:
        number = create.next_number(repo, org, project_chosen, projects)
    else:
        number = check_new_base(base)
        create.check_project_number(number, project_chosen, projects)
    chosen = check_variant(variant) if variant is not None else create.next_variant_number(repo, number, org, kind)
    pn = PN(org, number, chosen)
    if not record_store.exists(repo, pn):
        return NumberCheck(pn)
    try:
        record = record_store.load(repo, pn)
    except record_model.RegistryError:
        return NumberCheck(pn, True, "(its record can't be read)", "")
    return NumberCheck(pn, True, record.name, record.status)


@create.friendly
def suggest_variant_number(repo, base, org=None, kind=create.PART):
    """The variant number New Part (or New Assembly) would use right now for this part number."""
    repository.validate_repo(repo)
    return create.next_variant_number(repo, check_base(base), create.resolve_org(repo, org), kind)


@create.friendly
def list_variants(repo, base, org=None):
    """The records of every variant of a part number, in order (for showing what already exists)."""
    repository.validate_repo(repo)
    return record_store.load_variants(repo, check_base(base), create.resolve_org(repo, org))
