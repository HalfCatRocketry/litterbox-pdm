"""
generate_files.py - Generate STEP/PDF into the vault, and making them after a release.

The STEP and PDF belong to the part's working revision, in the cad folder (exporting/step_pdf.py makes them):

- A part you have checked out: they are made in your copy, its record notes them, and both go up with your next
  Check In (you already hold the locks).
- A part nobody has checked out: Litterbox locks its record, gets the latest, makes them, and uploads them with the
  record in one commit, then gives the lock back. This is how a released part gets its files.
- A part someone else has checked out, one waiting for sign-offs, or one with changes nobody checked in: refused.

A released revision takes new files only when they are flagged as needed (records/record_exports.py) or it doesn't
have them yet, unless an Admin makes them again (`force`). after_release() makes them for parts just released, and
never raises: a release is never held up by SolidWorks, the part stays flagged instead. It also saves a released
assembly's BOM with it (parts/release_bom.py), which needs no SolidWorks.
"""

from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.exporting import step_pdf
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.parts import permission_check
from litterbox.parts import release_bom
from litterbox.records import record_exports
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store


GENERATE, REMAKE = "generate_files", "remake_files"     # the permissions: any member, and Admins only


@dataclass
class Generated:
    done: list = field(default_factory=list)        # [(pn, [vault paths of the files made])]
    failed: list = field(default_factory=list)      # [(pn, why)]
    notes: list = field(default_factory=list)       # parts left out before starting, and why
    boms: list = field(default_factory=list)        # after a release: [(pn, vault path)] of the BOMs saved
    bom_failed: list = field(default_factory=list)  # after a release: [(pn, why)] the BOM wasn't saved


def up_to_date(needed, existing_kinds, possible):
    """A released revision's files are up to date when none are flagged as needed and it has every kind its files
    allow."""
    return not needed and all(kind in existing_kinds for kind in possible)


def refusal(record, holder, changed, files, force=False):
    """Why Litterbox won't make this part's files in the vault, or "" if it will. `holder` is ("you" or "other",
    name) for its lock, or None; `changed`: its files have changes not checked in; `files`: its working revision's
    files."""
    if record.status == record_model.STATUS_VOID:
        return "It is void."
    if record.pending:
        return "It is waiting for sign-offs."
    if holder and holder[0] != "you":
        return f"It is checked out by {holder[1]}."
    if not holder and changed:
        return "Its files have changes that are not checked in."
    if record.status == record_model.STATUS_RELEASED and not force:
        possible = step_pdf.possible_kinds(files)
        existing_kinds = [kind for kind in possible if step_pdf.existing(kind, files)]
        if up_to_date(record_exports.needed(record, possible), existing_kinds, possible):
            return "Its released STEP and PDF are up to date. An Admin can make them again."
    return ""


def generate(repo, pns, kinds, force=False, backend_factory=None):
    """Make the STEP and/or PDF (`kinds`) of these parts' working revisions in the vault. Returns Generated."""
    repository.validate_repo(repo)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, REMAKE if force else GENERATE)
    permission_check.check_parts(repo, pns, REMAKE if force else GENERATE)
    pns = batch_core.unique_pns(pns)
    result = Generated()
    locks = lfs_locks.get_locks(repo, strict=True)
    modified = repository.get_modified(repo)
    index = record_files.cad_index(repo)
    mine, free = [], []
    for pn in pns:
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            result.failed.append((pn, str(e)))
            continue
        revisions = index.get(pn, {})
        files = revisions.get(record.revision, [])
        holder = locks.get(record_store.record_relpath(pn).lower())
        changed = any(f.lower() in modified for fs in revisions.values() for f in fs)
        why = refusal(record, holder, changed, files, force)
        if why:
            result.failed.append((pn, why))
        else:
            (mine if holder else free).append(pn)
    for group, work in ((mine, lambda: _into_checkout(repo, user, mine, kinds, force, backend_factory, result)),
                        (free, lambda: _with_upload(repo, free, kinds, force, backend_factory, result))):
        if group:
            try:
                work()
            except LitterboxError as e:             # SolidWorks missing, the upload refused...: these parts fail
                result.failed += [(pn, str(e)) for pn in group if pn not in dict(result.done)]
    return result


def _jobs(repo, pns, kinds, result):
    jobs, notes = step_pdf.jobs_for(repo, pns, kinds, in_vault=True)
    result.notes += notes
    return jobs


def _vault_made(made):
    """step_pdf's {kind: details} with each file as its vault path."""
    return {kind: dict(details, file=f"{layout.CAD_DIR_NAME}/{details['file']}") for kind, details in made.items()}


def _into_checkout(repo, user, pns, kinds, force, backend_factory, result):
    """Parts you have checked out: make the files in your copy and note them in the records; Check In uploads both."""
    jobs = _jobs(repo, pns, kinds, result)
    made = step_pdf.make(repo, jobs, Path(repo) / layout.CAD_DIR_NAME, backend_factory)
    for job in jobs:
        files = made.made.get(job.pn)
        if files:
            record = record_store.load(repo, job.pn)
            record_exports.record_made(record, user, job.revision, _vault_made(files), job.possible, forced=force)
            record_store.save(repo, record)
            result.done.append((job.pn, [details["file"] for details in _vault_made(files).values()]))
        if job.pn in made.errors:
            result.failed.append((job.pn, made.errors[job.pn]))


def _with_upload(repo, pns, kinds, force, backend_factory, result):
    """Parts nobody has checked out: lock each record, get the latest, make the files, upload files and records in
    one commit."""
    outcome = {}

    def prepare(_user):
        jobs = _jobs(repo, pns, kinds, result)
        made = step_pdf.make(repo, jobs, Path(repo) / layout.CAD_DIR_NAME, backend_factory)
        outcome.update({job.pn: (job, made.made.get(job.pn, {}), made.errors.get(job.pn)) for job in jobs})
        return [f"{layout.CAD_DIR_NAME}/{details['file']}" for files in made.made.values() for details in files.values()]

    def edit(record, user):
        if record.pn not in outcome:
            raise record_model.RegistryError("It has no model or drawing to make them from.")
        job, files, error = outcome[record.pn]
        if not files:
            raise record_model.RegistryError(error or "Nothing was made.")
        if record.revision != job.revision:
            raise record_model.RegistryError(f"{record.pn} is now at Rev {record.revision}. Try again.")
        record_exports.record_made(record, user, job.revision, _vault_made(files), job.possible, forced=force)

    items = [(pn, REMAKE if force else GENERATE, edit, f"{pn}: STEP/PDF made") for pn in pns]
    batch = batch_core.edit_records(repo, items, prepare=prepare)
    for pn in pns:
        if pn in batch.results:
            _job, files, error = outcome[pn]
            result.done.append((pn, [details["file"] for details in _vault_made(files).values()]))
            if error:
                result.failed.append((pn, error))
        elif pn in batch.errors:
            result.failed.append((pn, str(batch.errors[pn])))
    if batch.notice:
        result.failed.append(("Locks", batch.notice))


def after_release(repo, pns, backend_factory=None):
    """For the parts among these that were just released (the release is their latest event): save each
    assembly's BOM with it, then make the STEP and PDF of those flagged for them, each uploaded at once. Never raises:
    if SolidWorks isn't there or fails, the parts stay flagged and the reason is in Generated.failed (and a BOM
    that couldn't be saved is in Generated.bom_failed)."""
    released, flagged = [], []
    for pn in pns:                          # decided first: saving the BOM adds an event after the release
        try:
            record = record_store.load(repo, pn)
        except (record_model.RegistryError, LitterboxError):
            continue
        last = record.history[-1].get("event") if record.history else None
        if not record.pending and last == record_model.EVENT_RELEASED:
            released.append(pn)
            if record_exports.is_flagged(record):
                flagged.append(pn)
    boms, bom_failed = [], []
    if released:
        try:
            boms, bom_failed = release_bom.save(repo, released)
        except Exception as e:              # anything at all: the release itself is already done
            diagnostics.LOG(f"Could not save the BOM after release of {', '.join(map(str, released))}: {e}")
            bom_failed = [(pn, str(e)) for pn in released]
    result = Generated()
    if flagged:
        try:
            result = generate(repo, flagged, record_exports.KINDS, backend_factory=backend_factory)
        except Exception as e:              # anything at all: the release itself is already done
            diagnostics.LOG(f"Could not make STEP/PDF after release of {', '.join(map(str, flagged))}: {e}")
            result.failed = [(pn, str(e)) for pn in flagged]
    result.boms, result.bom_failed = boms, bom_failed
    return result
