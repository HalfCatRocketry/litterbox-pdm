"""
Pure rules: part numbers, revisions, numbering order. Never runs git, never touches files.

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
