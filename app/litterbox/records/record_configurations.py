"""
record_configurations.py - each revision's configurations, as its record keeps them (the record's `configurations`):
the file's own configurations, which configuration of each part an assembly uses, and the name Litterbox gave the
file's only configuration (core/configuration_names.py). Read at check-in with SolidWorks open
(references/reference_reader.py).

    configurations:
      A:
        own:                          the model's configurations, in its order, with SolidWorks' ID for each
        - {name: Bracket, id: 0}
        - {name: Long, id: 1}
        named: Bracket                the name Litterbox gave "Default" (renamed again when the part's Name changes)
        uses:                         an assembly: the configurations of each part it uses
          HCR-00005-001_A: [Long]

A file with several configurations is still one part: they are checked out, revised and released together. The IDs
tell a renamed configuration (same ID, new name: assemblies follow it) from a deleted one (its ID is gone:
assemblies that used it quietly show another), so check-in can warn about the second (parts/configuration_check.py).
A revision missing from the section hasn't been read. Revise carries a revision's entry on to the next.
"""

from litterbox.core.revision_letters import check_revision


def _own(rev, entries):
    if not isinstance(entries, list):
        raise ValueError(f"'configurations' for Rev {rev} must list its own configurations.")
    found = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            raise ValueError(f"'configurations' for Rev {rev} must give each configuration's name.")
        found.append({"name": entry["name"], "id": int(entry["id"]) if entry.get("id") is not None else None})
    return found


def _uses(rev, uses):
    if not isinstance(uses, dict) or not all(isinstance(names, list) for names in uses.values()):
        raise ValueError(f"'configurations' for Rev {rev} must list the configurations of each part it uses.")
    return {str(stem): sorted({str(name) for name in names}) for stem, names in uses.items()}


def parse(value):
    """{revision: {"own": [{name, id}], "named": text, "uses": {stem: [names]}}} from a record's `configurations`,
    checked. Raises ValueError (record_model makes it a RegistryError)."""
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError("'configurations' must give each revision's configurations.")
    clean = {}
    for rev, entry in value.items():
        rev = check_revision(str(rev))                      # PNError is a ValueError too
        if not isinstance(entry, dict):
            raise ValueError(f"'configurations' for Rev {rev} must say what its configurations are.")
        clean[rev] = {"own": _own(rev, entry.get("own") or []), "named": str(entry.get("named") or ""),
                      "uses": _uses(rev, entry.get("uses") or {})}
    return clean


def to_data(configurations):
    """The record's section, in a steady order, leaving out what is empty."""
    data = {}
    for rev, entry in configurations.items():
        out = {"own": [{"name": c["name"], "id": c["id"]} if c.get("id") is not None else {"name": c["name"]}
                       for c in entry.get("own", [])]}
        if entry.get("named"):
            out["named"] = entry["named"]
        if entry.get("uses"):
            out["uses"] = {stem: sorted(names) for stem, names in sorted(entry["uses"].items(),
                                                                          key=lambda item: item[0].lower())}
        data[rev] = out
    return data


def entry(record, revision=None):
    """The revision's entry ({} if it hasn't been read)."""
    return record.configurations.get(revision or record.revision, {})


def names(record, revision=None):
    """The names of the revision's own configurations ([] if not read)."""
    return [c["name"] for c in entry(record, revision).get("own", [])]


def named(record, revision=None):
    """The name Litterbox last gave the revision's only configuration ("" for none)."""
    return entry(record, revision).get("named", "")


def uses(record, revision=None):
    """{stem: [configuration names]} the revision's assembly uses ({} if not read, or not an assembly)."""
    return dict(entry(record, revision).get("uses", {}))


def set_configurations(record, own, used=None, revision=None):
    """Keep what was read for a revision: `own` [{name, id}] and, for an assembly, `used` {stem: [names]}. The
    name Litterbox gave it is kept while that configuration is still there. Returns True if anything changed."""
    revision = revision or record.revision
    before = record.configurations.get(revision)
    kept = (before or {}).get("named", "")
    own = [{"name": str(c["name"]), "id": c.get("id")} for c in own]
    new = {"own": own, "named": kept if kept in {c["name"] for c in own} else "",
           "uses": {str(stem): sorted(set(names)) for stem, names in (used or {}).items()}}
    record.configurations[revision] = new
    return before != new


def set_named(record, name, revision=None):
    """Litterbox has renamed the revision's only configuration to `name`."""
    revision = revision or record.revision
    record.configurations.setdefault(revision, {"own": [], "named": "", "uses": {}})["named"] = name


def forget(record, revision=None):
    """The revision's model changed without being read: its configurations are no longer known. The name Litterbox
    gave its configuration is kept, so a later Name change can still find that configuration."""
    revision = revision or record.revision
    kept = named(record, revision)
    record.configurations.pop(revision, None)
    if kept:
        record.configurations[revision] = {"own": [], "named": kept, "uses": {}}


def carry_on(record, previous, revision):
    """Revise: the new revision starts as a copy of the previous one."""
    if previous in record.configurations:
        old = record.configurations[previous]
        record.configurations[revision] = {"own": [dict(c) for c in old.get("own", [])],
                                           "named": old.get("named", ""),
                                           "uses": {stem: list(names) for stem, names in old.get("uses", {}).items()}}
