"""
part_number.py - part numbers like HCR-00042-001: building, reading and checking them.

{ORG}-{BASE}-{VARIANT}. How many digits the base and variant are written with is a setting of each vault;
configure() sets it (vault/config.apply calls it), and MAX_BASE / MAX_VARIANT follow. They are module-level
settings: always read them as part_number.MAX_BASE at the moment you need them, never copy them.
"""

import re
from dataclasses import dataclass


DEFAULT_BASE_DIGITS = 5          # what a vault with no setting uses (so existing vaults never change)


NEW_VAULT_BASE_DIGITS = 6        # what the Create new vault dialog suggests for a new one


DEFAULT_VARIANT_DIGITS = 3


BASE_DIGITS_RANGE = (1, 9)


VARIANT_DIGITS_RANGE = (1, 4)


MIN_BASE = 1


MIN_VARIANT = 1


# The active settings. Change them only through configure().
BASE_DIGITS = DEFAULT_BASE_DIGITS


VARIANT_DIGITS = DEFAULT_VARIANT_DIGITS


MAX_BASE = 10 ** BASE_DIGITS - 1


MAX_VARIANT = 10 ** VARIANT_DIGITS - 1


# [0-9] instead of \d so that only plain digits are accepted.
# Bases with the right number of digits OR MORE are read, so a part that has
# outgrown the digit count still shows up instead of silently disappearing.
_ORG_RE = re.compile(r"[A-Za-z]{2,4}")


_PN_RE = FILE_RE = _SHORT_RE = None


def _check_digit_count(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise PNError(f"{label} must be a whole number from {low} to {high}.")
    return value


def configure(base_digits=DEFAULT_BASE_DIGITS, variant_digits=DEFAULT_VARIANT_DIGITS):
    """Set how many digits the base and variant are written with (called by config.apply)."""
    global BASE_DIGITS, VARIANT_DIGITS, MAX_BASE, MAX_VARIANT, _PN_RE, FILE_RE, _SHORT_RE
    base_digits = _check_digit_count(base_digits, "pn_base_digits", *BASE_DIGITS_RANGE)
    variant_digits = _check_digit_count(variant_digits, "pn_variant_digits", *VARIANT_DIGITS_RANGE)
    BASE_DIGITS, VARIANT_DIGITS = base_digits, variant_digits
    MAX_BASE, MAX_VARIANT = 10 ** base_digits - 1, 10 ** variant_digits - 1
    body = rf"([A-Za-z]{{2,4}})-([0-9]{{{base_digits},}})-([0-9]{{{variant_digits}}})"
    _PN_RE = re.compile(body)
    _SHORT_RE = re.compile(rf"([0-9]{{{base_digits},}})-([0-9]{{{variant_digits}}})")
    FILE_RE = re.compile(body + r"_([A-Za-z]{1,3})\.([A-Za-z0-9]+)")


configure()


def format_base(number):
    return f"{number:0{BASE_DIGITS}d}"


def format_variant(number):
    return f"{number:0{VARIANT_DIGITS}d}"


class PNError(ValueError):
    """Raised for an invalid part number. The message is safe to show to a user."""


def _to_int(value, label):
    """Accept an int, or text such as '42' or '00042', and return an int."""
    if isinstance(value, bool):
        raise PNError(f"{label} must be a whole number.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    raise PNError(f"{label} must be a whole number.")


def check_org(value):
    text = str(value).strip().upper()
    if not _ORG_RE.fullmatch(text):
        raise PNError("Org code must be 2 to 4 letters (for example HCR).")
    return text


def check_base(value):
    number = _to_int(value, "Part number")
    if number < MIN_BASE:
        raise PNError(f"Part number must be {MIN_BASE} or higher.")
    return number


def check_new_base(value):
    """For numbers being CREATED: like check_base, but also not beyond what the digit count allows."""
    number = check_base(value)
    if number > MAX_BASE:
        raise PNError(f"Part number {number} has more than {BASE_DIGITS} digits. "
                      f"The highest part number this vault can hold is {MAX_BASE}.")
    return number


def check_variant(value):
    number = _to_int(value, "Variant number")
    if not (MIN_VARIANT <= number <= MAX_VARIANT):
        raise PNError(f"Variant number must be between {format_variant(MIN_VARIANT)} and {format_variant(MAX_VARIANT)}.")
    return number


@dataclass(frozen=True, order=True)
class PN:
    """One part number. Frozen, so it can be used in sets and as a dict key.

        PN("hcr", 42, 1)   ->   str(...) is "HCR-00042-001"
    """
    org: str
    base: int
    variant: int

    def __post_init__(self):
        # Clean the values up (uppercase the org, turn "42" into 42, reject bad ones).
        object.__setattr__(self, "org", check_org(self.org))
        object.__setattr__(self, "base", check_base(self.base))
        object.__setattr__(self, "variant", check_variant(self.variant))

    def __str__(self):
        return f"{self.org}-{format_base(self.base)}-{format_variant(self.variant)}"

    @property
    def short(self):
        """The number without the org, for lists and records: '00042-001'."""
        return f"{format_base(self.base)}-{format_variant(self.variant)}"


def parse(text):
    """Turn 'HCR-00042-001' (any capitalization) into a PN. Raises PNError if invalid."""
    match = _PN_RE.fullmatch(str(text).strip())
    if not match:
        raise PNError(f"'{text}' is not a valid part number. Expected something like "
                      f"HCR-{format_base(42)}-{format_variant(1)}.")
    org, base, variant = match.groups()
    return PN(org, int(base), int(variant))


def try_parse(text):
    """Like parse(), but returns None instead of raising."""
    try:
        return parse(text)
    except PNError:
        return None


def parse_short(text, org):
    """Turn '00042-001' plus the org ('HCR') into a PN. A full 'HCR-00042-001' is accepted too."""
    text = str(text).strip()
    match = _SHORT_RE.fullmatch(text)
    if match:
        return PN(org, int(match.group(1)), int(match.group(2)))
    full = try_parse(text)
    if full:
        return full
    raise PNError(f"'{text}' is not a valid part number. Expected something like "
                  f"{format_base(42)}-{format_variant(1)}.")
