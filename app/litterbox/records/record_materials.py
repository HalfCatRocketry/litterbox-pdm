"""
record_materials.py - each revision's material, as SolidWorks has it assigned to the part, kept in the record:

    materials:
      A: Chrome Stainless Steel
      B: ''                 read, and SolidWorks has no material assigned

Read when a part's model is checked in with SolidWorks open, or by Update Material (parts/part_materials.py). A
revision missing from the section hasn't been read yet; it needs updating when it has a part file (.SLDPRT, see
record_lifecycle.material_needs_update). Assemblies, drawings, non-CAD parts and documents have none. Litterbox
versions before 0.5.3 keep the section without reading it. It has no record_model import (record_model reads it).
"""

from litterbox.core.revision_letters import check_revision

MAX_LENGTH = 200            # longer than any SolidWorks material name


def parse(value):
    """{revision: material} from a record's `materials`, checked. Raises ValueError (record_model makes it a
    RegistryError)."""
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError("'materials' must give each revision's material.")
    clean = {}
    for rev, name in value.items():
        rev = check_revision(str(rev))                      # PNError is a ValueError too
        if name is None:
            name = ""
        if not isinstance(name, str) or len(name) > MAX_LENGTH:
            raise ValueError(f"'materials' for Rev {rev} must be a material's name.")
        clean[rev] = " ".join(name.split())
    return clean


def material(record, revision=None):
    """A revision's material ('' when it has none, or it hasn't been read)."""
    return record.materials.get(revision or record.revision, "")


def is_read(record, revision=None):
    """True once a revision's material has been read (even if SolidWorks had none assigned)."""
    return (revision or record.revision) in record.materials


def set_material(record, name, revision=None):
    """Remember a revision's material as read from SolidWorks ('' for none assigned). Returns True if it changed."""
    revision = revision or record.revision
    name = " ".join(str(name or "").split())
    changed = record.materials.get(revision) != name
    record.materials[revision] = name
    return changed


def forget(record, revision=None):
    """The part file changed and its material couldn't be read: it needs updating."""
    record.materials.pop(revision or record.revision, None)
