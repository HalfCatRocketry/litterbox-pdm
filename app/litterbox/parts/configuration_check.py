"""
configuration_check.py - what check-in says about a model's configurations (records/record_configurations.py),
read with SolidWorks open (references/reference_reader.py). Nothing here refuses a check-in; each finding is a
warning shown when the check-in is done:

- a configuration that an assembly uses is gone from the part: SolidWorks would quietly show another one there. A
  renamed configuration keeps its ID and the assembly follows it, so only one whose ID is gone counts;
- the part's configurations have different materials: Litterbox keeps one material per revision, the active
  configuration's (the one it was saved in);
- the model is linked to an outside design table or equations file: Litterbox can't keep it with the revisions.
"""

from litterbox.records import record_configurations
from litterbox.references import reference_model
from litterbox.references import reference_queries


def deleted_names(before, after):
    """The names of configurations in `before` whose IDs aren't in `after` (both [{name, id}]). Entries without an
    ID can't be told apart from renamed ones, so they never count."""
    kept = {c.get("id") for c in after if c.get("id") is not None}
    return sorted(c["name"] for c in before if c.get("id") is not None and c["id"] not in kept)


def users_of(repo, pn, revision, names, records=None):
    """[(assembly, its revision, [names it uses])] for the assemblies that use this revision of the part in any of
    `names`."""
    if not names:
        return []
    records = records if records is not None else reference_model.load_records(repo)
    stem = f"{pn}_{revision}"
    found = []
    for use in reference_queries.where_used(repo, pn, records=records):
        if use.child_revision != revision:
            continue
        parent = records.get(use.parent)
        used = set(record_configurations.uses(parent, use.parent_revision).get(stem, [])) if parent else set()
        if used & set(names):
            found.append((use.parent, use.parent_revision, sorted(used & set(names))))
    return found


def _quoted(names):
    return ", ".join(f"'{name}'" for name in names)


def warnings(repo, pn, revision, before, read, records=None):
    """Sentences about the model's configurations. `before` is the revision's own configurations as the record had
    them ([{name, id}]); `read` is the reader's AssemblyRead (its configurations, or None if not read)."""
    if read is None or read.configurations is None:
        return []
    own, _used = read.configurations
    details = read.configuration_details or {}
    found = []
    for parent, parent_revision, names in users_of(repo, pn, revision, deleted_names(before, own), records):
        found.append(f"{pn} Rev {revision} no longer has the configuration{'s' if len(names) > 1 else ''} "
                     f"{_quoted(names)} that {parent} Rev {parent_revision} uses, so SolidWorks will show another "
                     "configuration there. Put it back, or change that assembly to use another one.")
    materials = {name: material for name, material in (details.get("materials") or {}).items()}
    if len(own) > 1 and len(set(materials.values())) > 1:
        active = details.get("active", "")
        listed = "; ".join(f"{name}: {material or 'none'}" for name, material in materials.items())
        kept = f" ({active}: {materials[active] or 'none'})" if active in materials else ""
        found.append(f"{pn}'s configurations have different materials ({listed}). Litterbox keeps one material per "
                     f"revision: the material of the configuration it was saved in{kept}.")
    for linked in details.get("linked") or []:
        found.append(f"{pn} is linked to {linked}. Litterbox doesn't keep that file with the part's revisions, so "
                     "changing it would change a released part without a new revision. Embed the design table or "
                     "equations in the part instead.")
    return found


def missing_after_update(child, old_revision, new_revision, used):
    """The configurations in `used` (names an assembly uses in `old_revision` of the part `child`, a record) that
    `new_revision` no longer has: by ID when both revisions were read with IDs, otherwise by name. [] when the new
    revision's configurations haven't been read."""
    old = record_configurations.entry(child, old_revision).get("own", [])
    new = record_configurations.entry(child, new_revision).get("own", [])
    if not used or not new:
        return []
    by_id = {c["name"]: c.get("id") for c in old}
    new_ids = {c.get("id") for c in new if c.get("id") is not None}
    new_names = {c["name"] for c in new}
    return sorted(name for name in used
                  if (by_id.get(name) not in new_ids if by_id.get(name) is not None and new_ids
                      else name not in new_names))
