"""
doc_number.py - document numbers like PROP-0001: a prefix the org sets for each document type, then a number with
at least four digits that grows past them (PROP-10000). Also the names of a document's files: PROP-0001_A.docx is
document PROP-0001, revision A.

A document number has two parts and a part number three (HCR-00042-001), so the two can never be mistaken for each
other. A prefix is 1 to 8 capital letters or digits, starting with a letter. ECO and T (for tickets) are kept for
Litterbox's own numbers.
"""

import re
from dataclasses import dataclass

from litterbox.core import revision_letters
from litterbox.core.part_number import PNError

DIGITS = 4
RESERVED_PREFIXES = {"ECO", "T"}
PREFIX_RE = re.compile(r"[A-Z][A-Z0-9]{0,7}")
NUMBER_RE = re.compile(r"([A-Z][A-Z0-9]{0,7})-(\d{4,})")
FILE_RE = re.compile(r"([A-Z][A-Z0-9]{0,7})-(\d{4,})_([A-Z]{1,3})\.([A-Za-z0-9]{1,10})", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class DocNumber:
    prefix: str
    number: int

    def __str__(self):
        return f"{self.prefix}-{self.number:0{DIGITS}d}"

    @property
    def short(self):
        """The same as str(): a document number has no org in front to leave out."""
        return str(self)


def check_prefix(text):
    """'prop' -> 'PROP'. Raises PNError if it can't be a prefix."""
    prefix = str(text or "").strip().upper()
    if not PREFIX_RE.fullmatch(prefix):
        raise PNError(f"'{text}' can't be a document prefix: use 1 to 8 letters or digits, starting with a letter "
                      "(for example PROP).")
    if prefix in RESERVED_PREFIXES:
        raise PNError(f"{prefix} is kept for Litterbox's own numbers. Choose another prefix.")
    return prefix


def parse(text):
    """'PROP-0001' -> DocNumber('PROP', 1). Raises PNError if it isn't a document number."""
    match = NUMBER_RE.fullmatch(str(text or "").strip().upper())
    if not match:
        raise PNError(f"'{text}' is not a document number like PROP-0001.")
    return DocNumber(match.group(1), int(match.group(2)))


def try_parse(text):
    try:
        return parse(text)
    except PNError:
        return None


def parse_filename(name):
    """'PROP-0001_A.docx' (a folder in front is ignored) -> (DocNumber, 'A', 'DOCX'). Raises PNError if invalid."""
    name = re.split(r"[\\/]", str(name).strip())[-1]
    match = FILE_RE.fullmatch(name)
    if not match:
        raise PNError(f"'{name}' is not a document file name like PROP-0001_A.docx.")
    prefix, number, revision, ext = match.groups()
    return (DocNumber(prefix.upper(), int(number)), revision_letters.check_revision(revision.upper()), ext.upper())


def try_parse_filename(name):
    try:
        return parse_filename(name)
    except PNError:
        return None


def filename(number, revision, extension):
    """filename(DocNumber('PROP', 1), 'a', '.docx') -> 'PROP-0001_A.docx'. The extension keeps its own case, so a
    file added as .docx stays .docx."""
    return f"{number}_{revision_letters.check_revision(revision)}.{str(extension).lstrip('.')}"


def next_number(prefix, used):
    """The number after the highest of `used` (DocNumbers) with this prefix: numbers are never reused."""
    return DocNumber(prefix, max((n.number for n in used if n.prefix == prefix), default=0) + 1)
