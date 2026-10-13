"""
pn.py - part-number logic for Litterbox.

This file is "pure logic": it never touches files or git, so it is easy to
test. It knows how to:
  * build and read part numbers like  HCR-00042-001
  * read CAD file names like          HCR-00042-001_A.SLDPRT  (the _A is the revision)
  * find the lowest unused number     (used by "New Part" / "New Variant")

Part number format:  {ORG}-{BASE}-{VARIANT}
  ORG      2 to 4 letters, always stored uppercase                       (HCR)
  BASE     whole number, written with base_digits digits (default 5)     (00042)
  VARIANT  whole number, written with variant_digits digits (default 3)  (001)

Revisions: A, B, C ... Z, AA, AB ... Every CAD file carries its revision after
an underscore. The revision is not part of the part number.

The two digit counts are settings of each vault (pn_base_digits and
pn_variant_digits in .litterbox/config.yaml). config.apply(repo) hands them to
configure() below, which is how the rest of the program learns them. They are
module-level settings, so only one set is active at a time; the engine applies
the right ones every time it starts work on a vault.
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
_PN_RE = _FILE_RE = _SHORT_RE = None


def _check_digit_count(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise PNError(f"{label} must be a whole number from {low} to {high}.")
    return value


def configure(base_digits=DEFAULT_BASE_DIGITS, variant_digits=DEFAULT_VARIANT_DIGITS):
    """Set how many digits the base and variant are written with (called by config.apply)."""
    global BASE_DIGITS, VARIANT_DIGITS, MAX_BASE, MAX_VARIANT, _PN_RE, _FILE_RE, _SHORT_RE
    base_digits = _check_digit_count(base_digits, "pn_base_digits", *BASE_DIGITS_RANGE)
    variant_digits = _check_digit_count(variant_digits, "pn_variant_digits", *VARIANT_DIGITS_RANGE)
    BASE_DIGITS, VARIANT_DIGITS = base_digits, variant_digits
    MAX_BASE, MAX_VARIANT = 10 ** base_digits - 1, 10 ** variant_digits - 1
    body = rf"([A-Za-z]{{2,4}})-([0-9]{{{base_digits},}})-([0-9]{{{variant_digits}}})"
    _PN_RE = re.compile(body)
    _SHORT_RE = re.compile(rf"([0-9]{{{base_digits},}})-([0-9]{{{variant_digits}}})")
    _FILE_RE = re.compile(body + r"_([A-Za-z]{1,3})\.([A-Za-z0-9]+)")


configure()


def format_base(number):
    return f"{number:0{BASE_DIGITS}d}"


def format_variant(number):
    return f"{number:0{VARIANT_DIGITS}d}"


class PNError(ValueError):
    """Raised for an invalid part number. The message is safe to show to a user."""


# ---------------------------------------------------------------------------
# Revisions: A, B, ... Z, AA, AB, ... (up to three letters)
# ---------------------------------------------------------------------------

FIRST_REVISION = "A"
MAX_REVISION_LETTERS = 3


def check_revision(value):
    """'b' -> 'B'. Raises PNError unless it is 1 to 3 letters."""
    text = str(value).strip().upper()
    if not re.fullmatch(rf"[A-Z]{{1,{MAX_REVISION_LETTERS}}}", text):
        raise PNError("A revision is 1 to 3 letters, for example A.")
    return text


def revision_number(label):
    """A -> 1, Z -> 26, AA -> 27 (so revisions can be compared in order)."""
    number = 0
    for letter in check_revision(label):
        number = number * 26 + (ord(letter) - 64)
    return number


def revision_label(number):
    """1 -> A, 26 -> Z, 27 -> AA"""
    if not isinstance(number, int) or number < 1:
        raise PNError("A revision number is 1 or higher.")
    letters = ""
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(65 + rest) + letters
    return check_revision(letters)


def next_revision(label, skip=()):
    """The letter after `label`, skipping any in `skip` (revisions that were cancelled are never reused)."""
    number = revision_number(label) + 1
    taken = {revision_number(x) for x in skip}
    while number in taken:
        number += 1
    return revision_label(number)


# ---------------------------------------------------------------------------
# Validation helpers. Each returns a cleaned-up value or raises PNError.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# The PN itself
# ---------------------------------------------------------------------------

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


def parse_filename(filename):
    """Turn 'HCR-00042-001_A.SLDPRT' into (PN, 'A', 'SLDPRT'). Raises PNError if invalid.

    A folder path in front of the name is ignored, so 'cad/HCR-00042-001_A.SLDPRT'
    and 'C:\\Litterbox\\hcr-litterbox\\cad\\HCR-00042-001_A.SLDPRT' both work.
    """
    name = re.split(r"[\\/]", str(filename).strip())[-1]
    match = _FILE_RE.fullmatch(name)
    if not match:
        raise PNError(f"'{name}' is not a Litterbox file name. Expected something like "
                      f"HCR-{format_base(42)}-{format_variant(1)}_A.SLDPRT (the _A is the revision).")
    org, base, variant, revision, ext = match.groups()
    return PN(org, int(base), int(variant)), check_revision(revision), ext.upper()


def try_parse_filename(filename):
    """Like parse_filename(), but returns None instead of raising."""
    try:
        return parse_filename(filename)
    except PNError:
        return None


def file_stem(pn, revision=FIRST_REVISION):
    """The file name without its extension: file_stem(PN('HCR', 42, 1), 'a') -> 'HCR-00042-001_A'"""
    return f"{pn}_{check_revision(revision)}"


def filename(pn, revision, extension):
    """filename(PN('HCR', 42, 1), 'a', 'sldprt')  ->  'HCR-00042-001_A.SLDPRT'"""
    return f"{file_stem(pn, revision)}.{str(extension).lstrip('.').upper()}"


# ---------------------------------------------------------------------------
# Finding the lowest unused number
# ---------------------------------------------------------------------------

def lowest_unused(used, minimum, maximum=None, label="number"):
    """Return the smallest whole number >= minimum that is not in `used`.

    Raises PNError if `maximum` is given and every number up to it is taken.
    """
    taken = set(used)
    number = minimum
    while number in taken:
        number += 1
    if maximum is not None and number > maximum:
        raise PNError(f"Every {label} from {minimum} to {maximum} is already used.")
    return number


def base_order(start=MIN_BASE):
    """Base numbers in the order they are handed out: `start` up to the highest the digits allow, then round to
    1 and up to just below `start`. So the start number is only the first point of a complete loop. Zero is never used."""
    start = start if MIN_BASE <= start <= MAX_BASE else MIN_BASE
    yield from range(start, MAX_BASE + 1)
    yield from range(MIN_BASE, start)


def free_bases(used_bases, count, start=MIN_BASE):
    """Up to `count` unused base numbers, in hand-out order (see base_order). Fewer if the vault is nearly full."""
    taken, found = set(used_bases), []
    if count <= 0:
        return found
    for number in base_order(start):
        if number not in taken:
            found.append(number)
            if len(found) == count:
                break
    return found


def next_base(used_bases, start=MIN_BASE):
    """The next unused base number: the lowest free one from `start` up, then, past the highest the digits allow,
    the lowest free one from 1 up to just below `start`. Numbers someone typed in by hand are simply treated as
    taken, so the sequence skips over them. Raises PNError when every part number is used."""
    found = free_bases(used_bases, 1, start)
    if not found:
        raise PNError(f"Every part number from {format_base(MIN_BASE)} to {format_base(MAX_BASE)} is already used "
                      "(voided parts keep theirs), so this vault has no part numbers left.")
    return found[0]


def next_variant(used_variants):
    """Lowest unused variant number for one base (1 to 999)."""
    return lowest_unused(used_variants, MIN_VARIANT, MAX_VARIANT, label="variant number")
