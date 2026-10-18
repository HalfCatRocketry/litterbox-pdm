"""
filenames.py - the names of CAD files in a vault: HCR-00042-001_A.SLDPRT is part HCR-00042-001,
revision A.
"""

import re

from litterbox.core import part_number
from litterbox.core import revision_letters


def parse_filename(filename):
    """Turn 'HCR-00042-001_A.SLDPRT' into (PN, 'A', 'SLDPRT'). Raises PNError if invalid.

    A folder path in front of the name is ignored, so 'cad/HCR-00042-001_A.SLDPRT'
    and 'C:\\Litterbox\\hcr-litterbox\\cad\\HCR-00042-001_A.SLDPRT' both work.
    """
    name = re.split(r"[\\/]", str(filename).strip())[-1]
    match = part_number.FILE_RE.fullmatch(name)
    if not match:
        raise part_number.PNError(f"'{name}' is not a Litterbox file name. Expected something like "
                      f"HCR-{part_number.format_base(42)}-{part_number.format_variant(1)}_A.SLDPRT (the _A is the revision).")
    org, base, variant, revision, ext = match.groups()
    return part_number.PN(org, int(base), int(variant)), revision_letters.check_revision(revision), ext.upper()


def try_parse_filename(filename):
    """Like parse_filename(), but returns None instead of raising."""
    try:
        return parse_filename(filename)
    except part_number.PNError:
        return None


def file_stem(pn, revision=revision_letters.FIRST_REVISION):
    """The file name without its extension: file_stem(PN('HCR', 42, 1), 'a') -> 'HCR-00042-001_A'"""
    return f"{pn}_{revision_letters.check_revision(revision)}"


def filename(pn, revision, extension):
    """filename(PN('HCR', 42, 1), 'a', 'sldprt')  ->  'HCR-00042-001_A.SLDPRT'"""
    return f"{file_stem(pn, revision)}.{str(extension).lstrip('.').upper()}"
