"""
Which parts an assembly uses, where a part is used, and keeping those up to date.

references.py - which parts an assembly uses, where a part is used, and keeping those up to date.

Each assembly's PN record lists the parts that each of its revisions uses:

    references:
      A:
      - HCR-00005-001_A
      - HCR-00006-001_B

Litterbox reads them from the assembly file (through SolidWorks) every time the assembly is checked
in, and again when a new revision is made. Because a released part never changes, "the assembly uses
HCR-00006-001_B" always means exactly the same files, forever.

WHERE USED   every assembly revision (released or not) that uses a part.
STALE        a reference is stale when the part has a newer RELEASED revision than the one the
             assembly uses. It is also flagged when the revision used is not released yet, was
             cancelled, or the part was voided or has no record.
REPLACE      Litterbox can point an assembly that is still in work at the latest released revision of
             parts it uses. Released assemblies are frozen: to change one, revise it.
"""
