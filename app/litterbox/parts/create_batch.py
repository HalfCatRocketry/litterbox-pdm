"""
create_batch.py - creating many part records at once, in one commit and one push (the importer uses
this).

create_planned creates exactly the numbers it is given, or raises NumbersTaken if someone took one first (nothing
of ours is left in git); create_many numbers a batch from the newest records and creates it, retrying.
"""

import os
from dataclasses import dataclass

from litterbox import diagnostics
from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.core.part_number import PN, PNError, check_new_base, check_variant, format_base
from litterbox.errors import LitterboxError
from litterbox.git import committing
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import create
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config


@dataclass
class PartSpec:
    """One part to create in a batch. Only the name is required.

    base / variant work as in new_part: leave them None to take the next free
    numbers, or give them to ask for particular ones.
    """
    name: str
    description: str = ""
    cots: bool = False
    imported: bool = False
    import_path: str = ""
    base: int = None
    variant: int = None
    configuration_named: str = ""   # the name its model's configuration was given when copied in (import_copying.py)


def _plan_batch(repo, specs, org):
    """Pick a PN for every spec, working from the records in the local copy. Raises CreateError.

    Specs that ask for a base are placed first (in order); the rest then take
    the lowest unused part numbers from the org's start number, skipping anything
    used in the vault or asked for elsewhere in this batch, and every project's block.
    """
    existing = record_store.list_pns(repo, org)
    taken = {(pn.base, pn.variant) for pn in existing}
    bases_used = {pn.base for pn in existing}
    start = config.get_start_number(repo)
    allowed = project_rules.outside_blocks(config.get_projects(repo))
    planned = [None] * len(specs)

    def label(index):
        return f"Item {index + 1} ({specs[index].name})"

    for index, spec in enumerate(specs):
        if spec.base is None:
            continue
        try:
            base = check_new_base(spec.base)
            variant = check_variant(spec.variant) if spec.variant is not None else None
        except PNError as e:
            raise create.CreateError(f"{label(index)}: {e}") from None
        if variant is not None:
            if (base, variant) in taken:
                raise create.CreateError(f"{label(index)}: {PN(org, base, variant)} is already in use"
                                  f"{create.describe_number(repo, org, base, variant)}.")
        else:
            variant = next(v for v in range(1, part_number.MAX_VARIANT + 2) if (base, v) not in taken)
            if variant > part_number.MAX_VARIANT:
                raise create.CreateError(f"{label(index)}: every variant of part number {format_base(base)} is used.")
        taken.add((base, variant))
        bases_used.add(base)
        planned[index] = PN(org, base, variant)

    candidate = start
    for index, spec in enumerate(specs):
        if spec.base is not None:
            continue
        while candidate in bases_used or not allowed(candidate):
            candidate += 1
        try:
            base = check_new_base(candidate)
            variant = check_variant(spec.variant) if spec.variant is not None else 1
        except PNError as e:
            raise create.CreateError(f"{label(index)}: {e}") from None
        taken.add((base, variant))
        bases_used.add(base)
        planned[index] = PN(org, base, variant)
    return planned


def _undo_batch(repo, record_paths, committed, pathspec):
    """Take back a batch that did not get pushed: our commit and our files. Never raises."""
    try:
        if committed:
            runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
        runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", f"--pathspec-from-file={pathspec}"], repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not fully undo the batch: {e}")
    for problem in read_only.delete_files(repo, record_paths):
        diagnostics.LOG(f"WARNING: could not delete {problem}")


def clean_specs(specs):
    """The specs with names and descriptions tidied and checked. Raises CreateError naming the bad item."""
    cleaned = []
    for index, spec in enumerate(specs, start=1):
        try:
            cleaned.append(PartSpec(
                create.clean_name(spec.name), create.clean_description(spec.description), bool(spec.cots),
                bool(spec.imported), str(spec.import_path or "").strip(), spec.base, spec.variant,
                str(getattr(spec, "configuration_named", "") or "")))
        except create.CreateError as e:
            raise create.CreateError(f"Item {index} ({spec.name or 'no name'}): {e}") from None
    return cleaned


class NumbersTaken(create.CreateError):
    """The planned numbers were taken by someone else just before our push. Nothing of ours is left in git."""


@create.friendly
def sync_latest(repo):
    """Download the latest records (the same step every creation starts with)."""
    repository.validate_repo(repo)
    try:
        create.sync_vault(repo)
    except LitterboxError as e:
        raise create.CreateError(f"Could not get the latest records from the vault, so nothing was created."
                          f"{create.online_hint(e)}\n\n{e}") from e


@create.friendly
def create_planned(repo, specs, planned, extra_paths=(), message=None):
    """ONE attempt at creating records for already-chosen PNs, plus other files, in ONE commit and ONE push.

    `specs` must already be cleaned (see clean_specs) and `planned` is one PN per spec.
    `extra_paths` are files (relative to the repo, like 'cad/HCR-00002-001_A.SLDPRT') that are
    committed together with the records. If anything fails, the commit and the records are taken
    back; the extra files are NOT deleted here (the caller made them, the caller removes them).
    If the push is rejected because the numbers were taken meanwhile, NumbersTaken is raised
    after the newest records have been downloaded, so the caller can plan again.
    """
    repository.validate_repo(repo)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "create")
    record_paths = [record_store.record_relpath(pn) for pn in planned]
    extras = list(extra_paths)
    pathspec = committing.write_pathspec(record_paths + extras)
    projects = config.get_projects(repo)                 # each record is in its number's project
    for project in sorted({create.project_name(projects, pn.base) for pn in planned}):
        permission_check.check_new_number(repo, project)   # a restricted project: its members only
    written, committed = [], False
    try:
        try:
            for pn, spec in zip(planned, specs):
                try:
                    record_store.create_record(repo, pn, spec.name, user, description=spec.description,
                                           cots=spec.cots, imported=spec.imported, import_path=spec.import_path,
                                           project=create.project_name(projects, pn.base),
                                           configuration_named=spec.configuration_named)
                except record_model.PNExistsError:
                    raise NumbersTaken(f"{pn} already exists in your copy of the vault.") from None
                written.append(record_store.record_relpath(pn))
            first, last = min(planned), max(planned)
            text = message or (f"Created {len(planned)} parts: {first} to {last}" if len(planned) > 1
                               else f"{first}: Created - {specs[0].name}")
            runner.run(["git", "add", f"--pathspec-from-file={pathspec}"], repo)
            runner.run(["git", "commit", "-m", text, f"--pathspec-from-file={pathspec}"], repo)
            committed = True
            runner.run(["git", "push"], repo)
        except NumbersTaken:
            _undo_batch(repo, written, committed, pathspec)
            raise
        except LitterboxError as e:
            _undo_batch(repo, written, committed, pathspec)
            if not committed:
                raise
            try:
                create.sync_vault(repo)
            except LitterboxError as sync_error:
                raise create.CreateError("The parts could not be created, and the latest records could not be got. "
                                  f"Nothing was changed.{create.online_hint(sync_error)}\n\n{sync_error}") from e
            raise NumbersTaken(f"The numbers could not be pushed (someone else may have just used one):\n\n{e}") from e
        except BaseException:
            _undo_batch(repo, written, committed, pathspec)
            raise
    finally:
        try:
            os.unlink(pathspec)
        except OSError:
            pass
    read_only.enforce_read_only(repo)
    return list(planned)


@create.friendly
def create_many(repo, specs, org=None, message=None):
    """Create many parts with ONE commit and ONE push, and return their PNs in the same order as `specs`.

    Everything is checked before anything is written, so a bad entry (no name, a
    number already in use) stops the whole batch with nothing changed. If someone
    else pushes at the same moment, the batch is taken back and numbered again
    from the newest records, the same way New Part does. Either every part in the
    batch is created or none is.
    """
    specs = list(specs)
    if not specs:
        return []
    repository.validate_repo(repo)
    cleaned = clean_specs(specs)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "create")
    try:
        create.sync_vault(repo)
    except LitterboxError as e:
        raise create.CreateError(f"Could not get the latest records from the vault, so nothing was created."
                          f"{create.online_hint(e)}\n\n{e}") from e
    org = create.resolve_org(repo, org)

    last_error = None
    for _attempt in range(create.ATTEMPTS):
        planned = _plan_batch(repo, cleaned, org)
        record_paths = [record_store.record_relpath(pn) for pn in planned]
        pathspec = committing.write_pathspec(record_paths)
        projects = config.get_projects(repo)                 # each record is in its number's project
        for project in sorted({create.project_name(projects, pn.base) for pn in planned}):
            permission_check.check_new_number(repo, project)   # a restricted project: its members only
        written, committed = [], False
        try:
            for pn, spec in zip(planned, cleaned):
                try:
                    record_store.create_record(repo, pn, spec.name, user, description=spec.description,
                                           cots=spec.cots, imported=spec.imported, import_path=spec.import_path,
                                           project=create.project_name(projects, pn.base),
                                           configuration_named=spec.configuration_named)
                except record_model.PNExistsError:
                    raise create.CreateError(f"{pn} already exists in your copy of the vault.") from None
                written.append(record_store.record_relpath(pn))
            first, last = min(planned), max(planned)
            text = message or (f"Created {len(planned)} parts: {first} to {last}" if len(planned) > 1
                               else f"{first}: Created - {cleaned[0].name}")
            runner.run(["git", "add", f"--pathspec-from-file={pathspec}"], repo)
            runner.run(["git", "commit", "-m", text, f"--pathspec-from-file={pathspec}"], repo)
            committed = True
            runner.run(["git", "push"], repo)
        except LitterboxError as e:
            _undo_batch(repo, written, committed, pathspec)
            if not committed:
                raise
            last_error = e
            diagnostics.LOG("The batch could not be pushed (someone else may have just used a number). Checking again...")
            try:
                create.sync_vault(repo)
            except LitterboxError as sync_error:
                raise create.CreateError("The parts could not be created, and the latest records could not be got. "
                                  f"Nothing was changed.{create.online_hint(sync_error)}\n\n{sync_error}") from e
            continue
        except BaseException:
            _undo_batch(repo, written, committed, pathspec)
            raise
        finally:
            try:
                os.unlink(pathspec)
            except OSError:
                pass

        read_only.enforce_read_only(repo)
        return planned

    raise create.CreateError(f"Could not create the parts after {create.ATTEMPTS} tries. The last error was:\n\n{last_error}")
