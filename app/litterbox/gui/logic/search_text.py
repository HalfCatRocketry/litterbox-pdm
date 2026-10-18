"""
search_text.py - what the search box's text matches. Capitals never matter.

    bracket      contains "bracket" anywhere ("Motor Bracket")
    Te*rt        * stands for any run of characters, and the pattern must match the whole value
                 ("Test Part", "TestPart", but not "My Test Part")
    *bracket*    contains, written with wildcards
    HCR-0000?    ? stands for exactly one character (also a whole-value match)
"""

import re

WILDCARDS = "*?"


def has_wildcards(text):
    return any(mark in (text or "") for mark in WILDCARDS)


def matcher(text):
    """A function value -> True if the value matches the search text. Empty text matches everything."""
    needle = (text or "").strip()
    if not needle:
        return lambda value: True
    if not has_wildcards(needle):
        lowered = needle.lower()
        return lambda value: lowered in str(value or "").lower()
    pattern = re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in needle),
                         re.IGNORECASE | re.DOTALL)
    return lambda value: pattern.fullmatch(str(value or "").strip()) is not None


def matches_any(match, values):
    """True if any of the values matches (a column can have several, like the full and the short part number)."""
    return any(match(value) for value in values)
