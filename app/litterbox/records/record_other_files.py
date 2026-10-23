"""
record_other_files.py - the files each assembly revision uses that aren't Litterbox parts, as its record keeps them
(the record's `other_files`): Toolbox parts, and files from outside the vault. They are read with the assembly's
references, at check-in with SolidWorks open and by Update BOM (references/reference_reader.py), and checked against
the team's Toolbox rule (core/toolbox_rules.py) at Check In and Release.

    other_files:
      A: []                                           read, and it uses nothing but Litterbox parts
      B:
      - file: C:\\SOLIDWORKS Data\\browser\\Ansi Inch\\...\\socket head cap screw_ai.sldprt
        toolbox: true
      - file: toolbox/browser/Ansi Inch/.../hex nut_ai.sldprt      (in the vault: the team's Toolbox)
        toolbox: true

A revision missing from the section hasn't been read since 0.6.0, or its assembly changed without SolidWorks to read
it: it needs Update BOM before a Toolbox rule can say it is fine. Revise carries a revision's entries on to the next.
"""

from litterbox.core.revision_letters import check_revision


def parse(value):
    """{revision: [{"file": text, "toolbox": bool}]} from a record's `other_files`, checked. Raises ValueError
    (record_model makes it a RegistryError)."""
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError("'other_files' must list the other files each revision uses.")
    clean = {}
    for rev, entries in value.items():
        rev = check_revision(str(rev))                      # PNError is a ValueError too
        if not isinstance(entries, list):
            raise ValueError(f"'other_files' for Rev {rev} must be a list.")
        found = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str) or not entry["file"].strip():
                raise ValueError(f"'other_files' for Rev {rev} must give each file's path.")
            found.append({"file": entry["file"], "toolbox": bool(entry.get("toolbox", False))})
        clean[rev] = found
    return clean


def to_data(other_files):
    """The record's section, in a steady order."""
    return {rev: [dict(e) for e in sorted(entries, key=lambda e: e["file"].lower())]
            for rev, entries in other_files.items()}


def is_read(record, revision=None):
    """True once a revision's other files have been read (even if it has none)."""
    return (revision or record.revision) in record.other_files


def entries(record, revision=None):
    """The revision's entries ([] if it has none, or they haven't been read)."""
    return list(record.other_files.get(revision or record.revision, []))


def set_other_files(record, found, revision=None):
    """Keep what was read for a revision ([{file, toolbox}]). Returns True if anything changed."""
    revision = revision or record.revision
    found = sorted(({"file": e["file"], "toolbox": bool(e.get("toolbox"))} for e in found),
                   key=lambda e: e["file"].lower())
    changed = record.other_files.get(revision) != found
    record.other_files[revision] = found
    return changed


def forget(record, revision=None):
    """The revision's assembly changed without being read: what it uses is no longer known."""
    record.other_files.pop(revision or record.revision, None)
