"""
reference_reader.py - reading which parts an assembly file uses and how many of each, and a part's material,
through the file's CAD program (cad/cad_programs.py). Check-in calls make_reader's reader for every part or assembly whose model changed.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from litterbox import layout
from litterbox.cad import cad_program
from litterbox.cad import cad_programs
from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.records import record_files
from litterbox.references import reference_model


@dataclass
class AssemblyRead:
    """What check-in read from a changed model: for an assembly, the parts it uses and how many of each (None if
    they couldn't be counted, so its BOM shows that it needs updating); for a part, its material (None if it couldn't
    be read, so it shows that it needs updating; '' for none assigned). `references` is None for a part."""
    references: list = None
    quantities: dict = None
    material: str = None
    other_files: list = None    # [{file, toolbox}]: what it uses that isn't a Litterbox part (record_other_files.py)


def can_start_cad_program():
    """Can "Update BOM" and "Update references" start the CAD program (SolidWorks) on this computer?"""
    return cad_programs.installed()


def new_backend(attach_only=False):
    return cad_programs.Backends(attach_only=attach_only)


def _assembly_files(repo, pn, revision, files):
    return [rel for rel in (files if files is not None else record_files.cad_files(repo, pn, revision))
            if file_types.extension(rel) in file_types.ASSEMBLY_EXTENSIONS]


def read_assembly_references(repo, pn, revision, backend, files=None):
    """The Litterbox parts that this revision's assembly files use, as a sorted list like
    ['HCR-00005-001_A']. Parts are not assemblies, so a revision with no .SLDASM gives [].
    Files that are not Litterbox files (a screw from a library, say) are ignored."""
    own = filenames.file_stem(pn, revision)
    found = set()
    for rel in _assembly_files(repo, pn, revision, files):
        for stored, located in backend.references(os.path.join(str(repo), rel)):
            stem = reference_model.stem_of_path(stored) or reference_model.stem_of_path(located)
            if stem and stem.lower() != own.lower():
                found.add(stem)
    return sorted(found, key=str.lower)


def _missing(path):
    """True if a component's file isn't really there: not on disk, or only a placeholder that was never
    downloaded. SolidWorks shows such a component as suppressed, which would make the count too low."""
    return not path or not os.path.exists(path) or read_only.is_pointer(Path(path))


def read_assembly_quantities(repo, pn, revision, backend, files=None, references=()):
    """How many of each Litterbox part this revision's assembly uses, as {stem: count}: one for each copy at
    the top of the assembly, leaving out suppressed copies and those excluded from the BOM. Every stem in
    `references` gets a count (0 if no copy counts). Raises LitterboxError if a component's file is missing
    or not downloaded, since the count would be wrong."""
    own = filenames.file_stem(pn, revision)
    counts = dict.fromkeys(references, 0)
    for rel in _assembly_files(repo, pn, revision, files):
        for path, state in backend.components(os.path.join(str(repo), rel)):
            stem = reference_model.stem_of_path(path)
            if state == cad_program.SUPPRESSED and _missing(path):
                raise LitterboxError(f"{os.path.basename(path) or 'A component'} could not be found, so the "
                                     "parts could not be counted.")
            if not stem or stem.lower() == own.lower():
                continue
            counts.setdefault(stem, 0)
            if state == cad_program.COUNTED:
                counts[stem] += 1
    return counts


def vault_relative(repo, path):
    """A path inside the vault as 'toolbox/browser/x.sldprt' (forward slashes), or None if it is outside it."""
    if not path:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(str(path)), os.path.abspath(str(repo)))
    except ValueError:                                  # another drive
        return None
    rel = rel.replace("\\", "/")
    return None if rel == ".." or rel.startswith("../") or os.path.isabs(rel) else rel


def vault_files_used(repo, pn, revision, backend, files=None):
    """The files in the vault, outside its cad folder, that this revision's assembly files use (the team's Toolbox
    parts), relative to the vault: what must be downloaded before the CAD program can load them."""
    cad = layout.CAD_DIR_NAME + "/"
    found = set()
    for rel in _assembly_files(repo, pn, revision, files):
        for stored, located in backend.references(os.path.join(str(repo), rel)):
            inside = vault_relative(repo, located or stored)
            if inside is not None and not inside.startswith(cad) and (Path(repo) / inside).is_file():
                found.add(inside)
    return sorted(found)


def read_other_files(repo, pn, revision, backend, files=None):
    """[{file, toolbox}] for the files this revision's assembly files use that aren't Litterbox parts in the vault's
    cad folder (records/record_other_files.py): Toolbox parts, and files from outside the vault. A file inside the
    vault is given relative to it; one outside it as the CAD program found it. A reference that can't be found at all
    is left out (counting the parts says so).

    A Toolbox part is given where the CAD program loaded it, not where the assembly says it is: SolidWorks loads every
    Toolbox part from the Toolbox folder this computer's SolidWorks is set to use, whatever folder the assembly was
    saved with (seen with SolidWorks 2024). So it is in the team's Toolbox exactly when this computer uses the team's
    Toolbox. The assembly's own reference to it (same file name) is that part, not another file. A backend without
    library_components (a program with no library of standard parts) has none."""
    own = filenames.file_stem(pn, revision).lower()
    cad = layout.CAD_DIR_NAME + "/"
    found = {}

    def add(path, toolbox):
        inside = vault_relative(repo, path)
        entry = inside if inside is not None else str(path)
        found.setdefault(entry.lower(), {"file": entry, "toolbox": toolbox})

    for rel in _assembly_files(repo, pn, revision, files):
        full = os.path.join(str(repo), rel)
        library_of = getattr(backend, "library_components", None)
        library = [path for path in (library_of(full) if library_of else []) if path]
        library_names = {file_types.file_name(path).lower() for path in library}
        for path in library:
            add(path, True)
        for stored, located in backend.references(full):
            path = located or stored
            if not located and not os.path.exists(stored or ""):
                continue                                # missing everywhere: nothing to say where it is
            if file_types.file_name(path).lower() in library_names:
                continue                                # a Toolbox part, given above where it was loaded from
            inside = vault_relative(repo, path)
            stem = reference_model.stem_of_path(stored) or reference_model.stem_of_path(located)
            if stem and stem.lower() == own:
                continue
            if stem and inside is not None and inside.startswith(cad):
                continue                                # a Litterbox part, where it belongs
            add(path, False)
    return sorted(found.values(), key=lambda e: e["file"].lower())


def read_part_material(repo, pn, revision, backend, files=None):
    """The material of this revision's part file (.SLDPRT) as SolidWorks has it, '' for none assigned, or None
    when the revision has no part file."""
    parts = [rel for rel in (files if files is not None else record_files.cad_files(repo, pn, revision))
             if file_types.extension(rel) in file_types.PART_EXTENSIONS]
    if not parts:
        return None
    return backend.material(os.path.join(str(repo), parts[0]))


def make_reader(backend=None, log=None):
    """A function to hand to checkin.checkin(): reads an assembly's references and counts its parts, or a part's
    material, when its model changed.

    reader(repo, pn, revision, changed_files) -> AssemblyRead, or None (nothing to update)
    A SolidWorks that can't be reached gives a warning and None: the check-in still goes ahead.
    Without a backend it attaches to a SolidWorks that is already running and never starts one; if
    none is running the references and counts are simply not updated this time. If only the counting fails,
    the references are kept and the quantities are left out.
    """
    log = log or (lambda text: None)

    def reader(repo, pn, revision, changed_files):
        assembly = any(file_types.extension(f) in file_types.ASSEMBLY_EXTENSIONS for f in changed_files)
        part = [f for f in changed_files if file_types.extension(f) in file_types.PART_EXTENSIONS]
        if not (assembly or part):
            return None
        mine = None
        try:
            with cad_programs.session():
                use = backend
                if use is None:
                    use = mine = new_backend(attach_only=True)
                try:
                    if not assembly:
                        try:
                            return AssemblyRead(material=read_part_material(repo, pn, revision, use, part))
                        except Exception as e:
                            log(f"WARNING: could not read the material of {pn}, so it needs updating "
                                f"(Part > Update Material). {e}")
                            return None
                    found = AssemblyRead(read_assembly_references(repo, pn, revision, use))
                    try:
                        found.quantities = read_assembly_quantities(repo, pn, revision, use,
                                                                    references=found.references)
                    except Exception as e:
                        log(f"WARNING: could not count the parts in {pn}, so its BOM needs updating. {e}")
                    try:
                        found.other_files = read_other_files(repo, pn, revision, use)
                    except Exception as e:
                        log(f"WARNING: could not tell whether {pn} uses Toolbox parts or files from outside the "
                            f"vault, so its BOM needs updating. {e}")
                    return found
                finally:
                    if mine is not None:
                        mine.close()
        except Exception as e:
            log(f"WARNING: could not read what {pn} uses, so its references were not updated. {e}" if assembly else
                f"WARNING: could not read the material of {pn}, so it needs updating (Part > Update Material). {e}")
            return None

    return reader
