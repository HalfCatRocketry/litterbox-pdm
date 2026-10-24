"""
import_copying.py - copying the files into the vault under their new names (SolidWorks Pack and Go,
so references follow), and checking afterwards that every copy points at the new names. Other files (exports
such as .STEP and .PDF) are copied as they are.
"""

import os
import shutil

from litterbox.core import file_types
from litterbox.core import filenames
from litterbox.parts import configuration_naming

from litterbox.importing import import_errors
from litterbox.importing import import_paths
from litterbox.records import record_store


def is_solidworks(path):
    return import_paths.ext_of(path) in file_types.CAD_EXTENSIONS


def check_cancel(cancel):
    if cancel is not None and cancel():
        raise import_errors.ImportCancelled("The import was cancelled. Nothing was added to the vault.")


def copy_everything(repo, plan, backend, cancel, progress, log):
    total = len(plan.order)
    for number, path in enumerate(plan.order, start=1):
        check_cancel(cancel)
        new_path = plan.copies[path]
        if progress:
            progress(number, total, f"Copying {os.path.basename(path)} as {os.path.basename(new_path)}")
        if is_solidworks(path):
            backend.copy(path, new_path)
        else:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.copyfile(path, new_path)
        if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
            raise import_errors.ImportFailed(f"The copy {new_path} was not created properly.")
        for stored, target in plan.repoints[import_paths.path_key(path)]:
            if not backend.repoint(new_path, stored, target):
                raise import_errors.ImportFailed(f"SolidWorks would not change the reference to {os.path.basename(stored)} "
                                   f"inside {os.path.basename(new_path)}.")


def verify(repo, plan, backend, before, log):
    """The copies must reference only each other, and the originals must be untouched."""
    cad = record_store.cad_dir(repo)
    for path in plan.order:
        new_path = plan.copies[path]
        if not os.path.exists(new_path):
            raise import_errors.ImportFailed(f"Missing after copying: {new_path}")
        if not is_solidworks(path):
            continue
        for stored, _found in backend.references(new_path):
            if import_paths.is_inside(stored, cad) or import_paths.path_key(stored) in plan.kept[import_paths.path_key(path)]:
                continue
            raise import_errors.ImportFailed(f"{os.path.basename(new_path)} still references {stored}, outside the vault.")
    changed = [p for p, snap in before.items() if snap != import_paths.snapshot_files([p])[p]]
    if changed:
        raise import_errors.ImportFailed("These original files changed while importing, which should never happen, so the "
                           "import was undone:\n" + "\n".join(changed[:8]))


def name_configurations(plan, backend, log):
    """Name each copied model's only configuration after its part (parts/configuration_naming.py), as New Part's
    first check-in would: {PN: the name given} for those renamed. A copy that can't be renamed is left as it is."""
    names = {pn: spec.name for pn, spec in zip(plan.pns, plan.specs)}
    named = {}
    for path in plan.order:
        new_path = plan.copies[path]
        if not file_types.is_part(new_path) and not file_types.is_assembly(new_path):
            continue
        parsed = filenames.try_parse_filename(os.path.basename(new_path))
        if parsed is None or parsed[0] not in names:
            continue
        try:
            given = configuration_naming.name_file(backend, new_path, names[parsed[0]])
        except Exception as e:
            log(f"NOTE: the configuration of {os.path.basename(new_path)} wasn't named after the part ({e}).")
            continue
        if given:
            named[parsed[0]] = given
    return named
