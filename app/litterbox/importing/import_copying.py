"""
import_copying.py - copying the files into the vault under their new names (SolidWorks Pack and Go,
so references follow), and checking afterwards that every copy points at the new names.
"""

import os

from litterbox.importing import import_errors
from litterbox.importing import import_paths
from litterbox.records import record_store


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
        backend.copy(path, new_path)
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
        for stored, _found in backend.references(new_path):
            if import_paths.is_inside(stored, cad) or import_paths.path_key(stored) in plan.kept[import_paths.path_key(path)]:
                continue
            raise import_errors.ImportFailed(f"{os.path.basename(new_path)} still references {stored}, outside the vault.")
    changed = [p for p, snap in before.items() if snap != import_paths.snapshot_files([p])[p]]
    if changed:
        raise import_errors.ImportFailed("These original files changed while importing, which should never happen, so the "
                           "import was undone:\n" + "\n".join(changed[:8]))
