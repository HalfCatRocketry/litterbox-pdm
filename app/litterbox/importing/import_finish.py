"""
import_finish.py - phase 3 of an import: copy the files in, create the records, commit and push, with a
journal so an import that stops half way can be put back.
"""

import uuid

from litterbox.git import lfs_download
from litterbox.git import read_only
from litterbox.importing import import_copying
from litterbox.importing import import_errors
from litterbox.importing import import_journal
from litterbox.importing import import_numbering
from litterbox.importing import import_paths
from litterbox.importing import import_plan
from litterbox.importing import import_prepare
from litterbox.importing import manifest as manifest_module
from litterbox.parts import create
from litterbox.parts import create_batch
from litterbox.parts import permission_check
from litterbox.records import record_store


ATTEMPTS = 3


def _conflict_message(conflicts):
    lines = [f"Row {c.index + 1}: {c.reason}" for c in conflicts]
    return ("These part numbers can't be used. Nothing was imported; change them and finish again:\n"
            + "\n".join(lines))


def finish(repo, prepared, dry_run=False, cancel=None, progress=None, log=print):
    """Do the import with the table as it stands. Returns a Result.

    First the part numbers are checked against the newest records. Automatic numbers that are
    taken are replaced by free ones; if a number the user typed is taken, PNConflict is raised
    before anything is copied (the table can be corrected and finish called again). Cancelling,
    errors and crashes leave nothing behind (see the top of this file).
    """
    mf, backend, proposal = prepared.manifest, prepared.backend, prepared.proposal
    items = prepared.items
    if not items:
        raise import_errors.ImportFailed("Nothing is selected, so there is nothing to import.")
    if not dry_run:
        permission_check.check_solidworks_version(repo, "import these files")     # SolidWorks copies them in
    originals = import_paths.snapshot_files([p for item in items for p in import_plan.item_files(item)])
    last_error = None
    renumbered = []
    for attempt in range(1, ATTEMPTS + 1):
        import_copying.check_cancel(cancel)
        state = import_numbering.refresh(repo, proposal, log)
        renumbered += state.renumbered
        if state.conflicts:
            raise import_errors.PNConflict(_conflict_message(state.conflicts), state.conflicts, renumbered)
        try:
            specs = create_batch.clean_specs([
                create_batch.PartSpec(name=e.name, description=e.description, cots=prepared.cots or e.item.cots,
                                imported=True, import_path=e.item.main_path) for e in proposal.entries])
        except create.CreateError as e:
            raise import_errors.ImportFailed(str(e)) from None
        pns = proposal.pns()
        plan = import_plan.build_plan(repo, items, specs, pns, prepared.refs, mf, prepared.allow_external)
        if dry_run:
            return import_plan.Result(pns=pns, warnings=plan.warnings, plan=plan, dry_run=True, version=prepared.version,
                          renumbered=renumbered)

        # Copies may point at parts already in the vault (imported before); SolidWorks needs those files themselves.
        new_targets = set(plan.copies.values())
        lfs_download.download(repo, sorted({import_paths.relative_path(repo, target)
                                            for entries in plan.repoints.values() for _stored, target in entries
                                            if target not in new_targets}), "parts this import uses")
        new_files = [import_paths.relative_path(repo, plan.copies[p]) for p in plan.order]
        record_paths = [record_store.record_relpath(pn) for pn in pns]
        token = uuid.uuid4().hex[:12]
        noun = "COTS parts" if prepared.cots else "parts"
        message = ((f"Imported {len(pns)} {noun}: {min(pns)} to {max(pns)}" if len(pns) > 1
                    else f"{pns[0]}: Imported{' COTS' if prepared.cots else ''} - {specs[0].name}")
                   + f"\n\nLitterbox-Import: {token}")
        import_journal.write_journal(repo, "copying", token, new_files, record_paths)
        try:
            import_copying.copy_everything(repo, plan, backend, cancel, progress, log)
            import_copying.verify(repo, plan, backend, originals, log)
            import_copying.check_cancel(cancel)
            if progress:
                progress(len(plan.order), len(plan.order), "Adding to the vault...")
            import_journal.write_journal(repo, "committing", token, new_files, record_paths)
            create_batch.create_planned(repo, specs, pns, extra_paths=new_files, message=message)
        except create_batch.NumbersTaken as e:
            last_error = e
            import_journal.recover(repo, log)
            log(f"Someone else used one of the part numbers just now (try {attempt} of {ATTEMPTS}); checking again.")
            continue
        except BaseException:
            import_journal.recover(repo, log)          # removes exactly what this import copied
            raise
        import_journal.clear_journal(repo)
        read_only.enforce_read_only(repo)
        for entry in proposal.entries:                      # the manifest keeps any edits made in the table
            entry.item.name, entry.item.description = entry.name, entry.description
        manifest_module.record_assignments(mf, items, pns)
        try:
            manifest_module.save(mf, prepared.manifest_path)
        except manifest_module.ManifestError as e:
            plan.warnings.append(f"The parts were imported, but the manifest could not be updated: {e}")
        return import_plan.Result(pns=pns, files=new_files, warnings=plan.warnings, plan=plan, version=prepared.version,
                      renumbered=renumbered)
    raise import_errors.ImportFailed(f"Part numbers kept being taken by other people. Nothing was imported. "
                       f"Try again.\n\n{last_error}")


def run(repo, manifest_path, backend=None, dry_run=False, allow_external=False, cancel=None,
        progress=None, log=print, org=None, gap=import_numbering.DEFAULT_GAP, jitter=import_numbering.DEFAULT_JITTER, rng=None, cots=False,
        project=None):
    """prepare() and finish() in one go, with the proposed numbers and names as they are (no table to edit).

    Raises ImportFailed (ImportCancelled if cancelled; PNConflict never happens here because
    nothing is typed in) with nothing left behind.
    """
    prepared = import_prepare.prepare(repo, manifest_path, backend, allow_external, cancel, progress, log, org, gap, jitter, rng, cots,
                                      project)
    try:
        return finish(repo, prepared, dry_run, cancel, progress, log)
    finally:
        prepared.close()
