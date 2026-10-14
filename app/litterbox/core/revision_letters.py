"""
revision_letters.py - revisions: A, B ... Z, AA, AB ... (at most three letters).

A revision is not part of the part number; every CAD file carries it after an underscore. Cancelled revisions are
never reused.
"""

import re

from litterbox.core import part_number


FIRST_REVISION = "A"


MAX_REVISION_LETTERS = 3


def check_revision(value):
    """'b' -> 'B'. Raises PNError unless it is 1 to 3 letters."""
    text = str(value).strip().upper()
    if not re.fullmatch(rf"[A-Z]{{1,{MAX_REVISION_LETTERS}}}", text):
        raise part_number.PNError("A revision is 1 to 3 letters, for example A.")
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
        raise part_number.PNError("A revision number is 1 or higher.")
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
