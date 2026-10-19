"""
numbering.py - which part number comes next.

Bases count up from the vault's start number to the highest the digits allow, then loop round to 1 and go up to
just below the start: the start number is only the first point of a full loop. Zero is never used, and a number
once used (voided parts included) is never handed out again. `allowed` (a test, base -> True/False) leaves numbers
out, such as the blocks set aside for projects (core/projects.py).
"""

from litterbox.core import part_number


def lowest_unused(used, minimum, maximum=None, label="number"):
    """Return the smallest whole number >= minimum that is not in `used`.

    Raises PNError if `maximum` is given and every number up to it is taken.
    """
    taken = set(used)
    number = minimum
    while number in taken:
        number += 1
    if maximum is not None and number > maximum:
        raise part_number.PNError(f"Every {label} from {minimum} to {maximum} is already used.")
    return number


def base_order(start=part_number.MIN_BASE):
    """Base numbers in the order they are handed out: `start` up to the highest the digits allow, then round to
    1 and up to just below `start`. So the start number is only the first point of a complete loop. Zero is never used."""
    start = start if part_number.MIN_BASE <= start <= part_number.MAX_BASE else part_number.MIN_BASE
    yield from range(start, part_number.MAX_BASE + 1)
    yield from range(part_number.MIN_BASE, start)


def free_bases(used_bases, count, start=part_number.MIN_BASE, allowed=None):
    """Up to `count` unused base numbers, in hand-out order (see base_order). Fewer if the vault is nearly full."""
    taken, found = set(used_bases), []
    if count <= 0:
        return found
    for number in base_order(start):
        if number not in taken and (allowed is None or allowed(number)):
            found.append(number)
            if len(found) == count:
                break
    return found


def base_after(number, steps, start=part_number.MIN_BASE):
    """The base number `steps` places along the hand-out loop (see base_order) from `number`."""
    start = start if part_number.MIN_BASE <= start <= part_number.MAX_BASE else part_number.MIN_BASE
    position = (number - start) % part_number.MAX_BASE
    return (start + (position + steps) % part_number.MAX_BASE - 1) % part_number.MAX_BASE + 1


def next_base(used_bases, start=part_number.MIN_BASE, allowed=None):
    """The next unused base number: the lowest free one from `start` up, then, past the highest the digits allow,
    the lowest free one from 1 up to just below `start`. Numbers someone typed in by hand are simply treated as
    taken, so the sequence skips over them. Raises PNError when every part number is used."""
    found = free_bases(used_bases, 1, start, allowed)
    if not found:
        raise part_number.PNError(f"Every part number from {part_number.format_base(part_number.MIN_BASE)} to {part_number.format_base(part_number.MAX_BASE)} is already used "
                      "(voided parts keep theirs), so this vault has no part numbers left.")
    return found[0]


def next_variant(used_variants, low=None, high=None):
    """Lowest unused variant number for one base, from `low` to `high` (default: every variant, 1 to 999). New Part
    and New Assembly each use their own range (see parts/create.py: variant_range)."""
    low = part_number.MIN_VARIANT if low is None else low
    high = part_number.MAX_VARIANT if high is None else high
    return lowest_unused(used_variants, low, high, label="variant number")
