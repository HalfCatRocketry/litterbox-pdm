"""
create.py - New Part and New Variant: creating part numbers.

Creating a part number means making its record file (PN-logs/HCR-00042-001.yaml),
committing it, and pushing it to the vault. Once it is pushed, the number is
yours, permanently, even if no CAD file is ever made for it.

    new_part(repo, "Front upright")                    next free part number, variant 001
    new_part(repo, "Front upright", base=500)          part number 500, lowest free variant
    new_part(repo, "Right hand", base=42)              next free variant of part number 42
    new_part(repo, "Right hand", base=42, variant=7)   variant 007 of part number 42 (if it is free)

(new_variant(repo, 42, "Right hand") is the same as new_part with base=42.)
All of them return the new PN. The numbers are always the lowest unused ones, and a
number that someone typed in by hand is simply treated as taken when the
sequence reaches it. Void numbers count as taken too, so a number is never
reused.

TWO PEOPLE AT THE SAME MOMENT
  Both of you may pick the same number. Whoever pushes first gets it. For the
  other person the push is rejected, so Litterbox quietly takes back its own
  commit, downloads the new records, and picks again. (If the number was typed in
  by hand, you are told it was just taken, since picking a different one for you
  would be wrong.)

Command line:
    python create.py <repo> part "name" [--description "..."] [--number N]
    python create.py <repo> variant <base> "name" [--description "..."] [--variant N]
    python create.py <repo> variants <base>      list the variants that exist
    python create.py <repo> next                 show what the next part number would be
"""

import argparse
import os
import sys
from functools import wraps
from pathlib import Path

from litterbox.vault import config
from litterbox.core import part_number
from litterbox.records import record_model
from litterbox.records import record_store
from dataclasses import dataclass

from litterbox.core.part_number import PN, PNError, check_base, check_new_base, check_org, check_variant, format_base, format_variant
from litterbox.errors import LitterboxError
from litterbox import diagnostics
from litterbox.parts import permission_check
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import committing
from litterbox.git import runner

MAX_NAME = 100
MAX_DESCRIPTION = 500
ATTEMPTS = 5            # how many times to pick a number again if someone else got there first


class CreateError(LitterboxError):
    """A part number could not be created. The message is safe to show to a user."""


def _friendly(func):
    """Make every public function raise only LitterboxError (CreateError is one)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (record_model.RegistryError, config.ConfigError, PNError) as e:
            raise CreateError(str(e)) from e
    return wrapper


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _clean_text(text, label, limit, required):
    text = " ".join(str(text or "").split())          # one line, single spaces
    if not text and required:
        raise CreateError(f"A {label} is required.")
    if len(text) > limit:
        raise CreateError(f"Keep the {label} under {limit} characters (it is {len(text)}).")
    return text


def _clean_name(text):
    return _clean_text(text, "name", MAX_NAME, required=True)


def _clean_description(text):
    return _clean_text(text, "description", MAX_DESCRIPTION, required=False)


def _org(repo, org):
    return check_org(org) if org else config.get_org(repo)


def _sync(repo):
    """Download the latest records. Local edits to checked-out files are set aside and put back."""
    runner.run(["git", "pull", "--rebase", "--autostash"], repo)


def _describe(repo, org, base, variant=None):
    """Who already has this number, for error messages."""
    try:
        records = record_store.load_variants(repo, base, org)
    except record_model.RegistryError:
        return ""
    if variant is not None:
        records = [r for r in records if r.pn.variant == variant]
    shown = ", ".join(f"{r.pn}: {r.name}" + (" [void]" if r.status == record_model.STATUS_VOID else "")
                      for r in records[:3])
    if len(records) > 3:
        shown += f", and {len(records) - 3} more"
    return f" ({shown})" if shown else ""


def _undo_creation(repo, record_path, committed):
    """Take back a creation that did not get pushed: our commit, and the file. Never raises.

    Only our one commit and our one new file are touched. Anything else in the
    folder, such as changes to parts you have checked out, is left alone.
    """
    try:
        if committed:
            runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
        runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--", record_path], repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not fully undo the creation of {record_path}: {e}")
    path = Path(repo) / record_path
    try:
        if path.exists():
            os.chmod(path, 0o644)
            path.unlink()
    except OSError as e:
        diagnostics.LOG(f"WARNING: could not delete {record_path}: {e}")


# ---------------------------------------------------------------------------
# The creation itself
# ---------------------------------------------------------------------------

def _create(repo, name, description, org, choose):
    """Create, commit and push one record. `choose(org)` returns the PN to try.

    choose() is called again after every rejected push, so it always works from
    the newest records. It raises CreateError if a number typed in by hand is taken.
    """
    repository.validate_repo(repo)
    name = _clean_name(name)
    description = _clean_description(description)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "create")
    try:
        _sync(repo)
    except LitterboxError as e:
        raise CreateError(f"Could not get the latest records from the vault, so nothing was created. "
                           f"Are you online?\n\n{e}") from e
    org = _org(repo, org)

    last_error = None
    for _attempt in range(ATTEMPTS):
        pn = choose(org)
        record_path = record_store.record_relpath(pn)
        try:
            record_store.create_record(repo, pn, name, user, description=description)
        except record_model.PNExistsError:
            raise CreateError(f"{pn} already exists in your copy of the vault.") from None

        committed = False
        try:
            runner.run(["git", "add", "--", record_path], repo)
            runner.run(["git", "commit", "-m", f"{pn}: Created - {name}", "--", record_path], repo)
            committed = True
            runner.run(["git", "push"], repo)
        except LitterboxError as e:
            _undo_creation(repo, record_path, committed)
            if not committed:
                raise
            last_error = e
            diagnostics.LOG(f"{pn} could not be pushed (someone else may have just used it). Checking again...")
            try:
                _sync(repo)
            except LitterboxError as sync_error:
                raise CreateError(
                    f"{pn} could not be created, and the vault can't be reached right now. "
                    f"Nothing was changed. Are you online?\n\n{sync_error}") from e
            continue
        except BaseException:
            _undo_creation(repo, record_path, committed)
            raise

        read_only.enforce_read_only(repo)          # the new record is read-only until someone checks it out
        return pn

    raise CreateError(f"Could not create a number after {ATTEMPTS} tries. The last error was:\n\n{last_error}")


# ---------------------------------------------------------------------------
# Many at once (used by the importer)
# ---------------------------------------------------------------------------

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


def _plan_batch(repo, specs, org):
    """Pick a PN for every spec, working from the records in the local copy. Raises CreateError.

    Specs that ask for a base are placed first (in order); the rest then take
    the lowest unused part numbers from the org's start number, skipping anything
    used in the vault or asked for elsewhere in this batch.
    """
    existing = record_store.list_pns(repo, org)
    taken = {(pn.base, pn.variant) for pn in existing}
    bases_used = {pn.base for pn in existing}
    start = config.get_start_number(repo)
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
            raise CreateError(f"{label(index)}: {e}") from None
        if variant is not None:
            if (base, variant) in taken:
                raise CreateError(f"{label(index)}: {PN(org, base, variant)} is already in use"
                                  f"{_describe(repo, org, base, variant)}.")
        else:
            variant = next(v for v in range(1, part_number.MAX_VARIANT + 2) if (base, v) not in taken)
            if variant > part_number.MAX_VARIANT:
                raise CreateError(f"{label(index)}: every variant of part number {format_base(base)} is used.")
        taken.add((base, variant))
        bases_used.add(base)
        planned[index] = PN(org, base, variant)

    candidate = start
    for index, spec in enumerate(specs):
        if spec.base is not None:
            continue
        while candidate in bases_used:
            candidate += 1
        try:
            base = check_new_base(candidate)
            variant = check_variant(spec.variant) if spec.variant is not None else 1
        except PNError as e:
            raise CreateError(f"{label(index)}: {e}") from None
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
    for record_path in record_paths:
        path = Path(repo) / record_path
        try:
            if path.exists():
                os.chmod(path, 0o644)
                path.unlink()
        except OSError as e:
            diagnostics.LOG(f"WARNING: could not delete {record_path}: {e}")


def clean_specs(specs):
    """The specs with names and descriptions tidied and checked. Raises CreateError naming the bad item."""
    cleaned = []
    for index, spec in enumerate(specs, start=1):
        try:
            cleaned.append(PartSpec(
                _clean_name(spec.name), _clean_description(spec.description), bool(spec.cots),
                bool(spec.imported), str(spec.import_path or "").strip(), spec.base, spec.variant))
        except CreateError as e:
            raise CreateError(f"Item {index} ({spec.name or 'no name'}): {e}") from None
    return cleaned


class NumbersTaken(CreateError):
    """The planned numbers were taken by someone else just before our push. Nothing of ours is left in git."""


@_friendly
def sync_latest(repo):
    """Download the latest records (the same step every creation starts with)."""
    repository.validate_repo(repo)
    try:
        _sync(repo)
    except LitterboxError as e:
        raise CreateError(f"Could not get the latest records from the vault, so nothing was created. "
                          f"Are you online?\n\n{e}") from e


@_friendly
def plan_numbers(repo, specs, org=None):
    """The PNs a batch would get right now, in order. Reads the local copy only and writes nothing,
    so nothing is reserved: the numbers become yours only when create_planned pushes them."""
    repository.validate_repo(repo)
    return _plan_batch(repo, list(specs), _org(repo, org))


@_friendly
def create_planned(repo, specs, planned, extra_paths=(), message=None):
    """ONE attempt at creating records for already-chosen PNs, plus other files, in ONE commit and ONE push.

    `specs` must already be cleaned (see clean_specs) and `planned` is one PN per spec.
    `extra_paths` are files (relative to the repo, like 'cad/HCR-00002-001.SLDPRT') that are
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
    written, committed = [], False
    try:
        try:
            for pn, spec in zip(planned, specs):
                try:
                    record_store.create_record(repo, pn, spec.name, user, description=spec.description,
                                           cots=spec.cots, imported=spec.imported, import_path=spec.import_path)
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
                _sync(repo)
            except LitterboxError as sync_error:
                raise CreateError("The parts could not be created, and the vault can't be reached right now. "
                                  f"Nothing was changed. Are you online?\n\n{sync_error}") from e
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


@_friendly
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
        _sync(repo)
    except LitterboxError as e:
        raise CreateError(f"Could not get the latest records from the vault, so nothing was created. "
                          f"Are you online?\n\n{e}") from e
    org = _org(repo, org)

    last_error = None
    for _attempt in range(ATTEMPTS):
        planned = _plan_batch(repo, cleaned, org)
        record_paths = [record_store.record_relpath(pn) for pn in planned]
        pathspec = committing.write_pathspec(record_paths)
        written, committed = [], False
        try:
            for pn, spec in zip(planned, cleaned):
                try:
                    record_store.create_record(repo, pn, spec.name, user, description=spec.description,
                                           cots=spec.cots, imported=spec.imported, import_path=spec.import_path)
                except record_model.PNExistsError:
                    raise CreateError(f"{pn} already exists in your copy of the vault.") from None
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
                _sync(repo)
            except LitterboxError as sync_error:
                raise CreateError("The parts could not be created, and the vault can't be reached right now. "
                                  f"Nothing was changed. Are you online?\n\n{sync_error}") from e
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

    raise CreateError(f"Could not create the parts after {ATTEMPTS} tries. The last error was:\n\n{last_error}")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

@_friendly
def new_part(repo, name, description="", base=None, variant=None, org=None):
    """Create a new part number and return the PN.

    Leave `base` empty to take the lowest unused part number, or give a number
    to ask for a particular one. Leave `variant` empty to take the lowest unused
    variant of that part number (001 for a part number nobody has used), or give
    a number (1 to 999) to ask for that one. The part number does not have to
    exist yet: asking for 12345-501 is fine even if 12345-001 was never made.

    Numbers you ask for by name that are already taken give an error saying by what.
    """
    manual_base = check_new_base(base) if base is not None else None
    manual_variant = check_variant(variant) if variant is not None else None

    def choose(org):
        number = manual_base
        if number is None:
            number = check_new_base(record_store.next_free_base(repo, org, config.get_start_number(repo)))
        if manual_variant is None:
            return PN(org, number, record_store.next_free_variant(repo, number, org))
        if manual_variant in record_store.used_variants(repo, number, org):
            raise CreateError(
                f"{PN(org, number, manual_variant)} is already in use"
                f"{_describe(repo, org, number, manual_variant)}. "
                "Pick a different variant number, or leave it blank for the next free one.")
        return PN(org, number, manual_variant)

    return _create(repo, name, description, org, choose)


def new_variant(repo, base, name, description="", variant=None, org=None):
    """Create a new variant of a part number. The same as new_part with a part number given."""
    return new_part(repo, name, description, base=base, variant=variant, org=org)


# These two read your local copy only (no network). They are for showing a
# suggestion in a dialog; the real choice is always made again when you create.

@_friendly
def suggest_part_number(repo, org=None):
    """The part number New Part would use right now if the box were left empty."""
    repository.validate_repo(repo)
    return record_store.next_free_base(repo, _org(repo, org), config.get_start_number(repo))


@_friendly
def suggest_numbers(repo, base=None, org=None):
    """What New Part would use if the boxes were left empty: (part number, variant number).

    `base` is the part number typed so far, if any. The variant is 1 unless that
    part number is already in use, in which case it is the lowest unused variant.
    """
    repository.validate_repo(repo)
    org = _org(repo, org)
    number = check_base(base) if base is not None else record_store.next_free_base(
        repo, org, config.get_start_number(repo))
    return number, record_store.next_free_variant(repo, number, org)


@dataclass
class NumberCheck:
    pn: PN                  # the part number that would be created
    taken: bool = False     # True if a record with this part number already exists
    name: str = ""          # the name of the part that has it
    status: str = ""        # its status (in_work, released, void)


@_friendly
def check_numbers(repo, base=None, variant=None, org=None):
    """What New Part would create for these boxes, and whether that part number is free.

    Leave `base` or `variant` as None for a box left empty (the suggested number is used).
    Reads your local copy only. New Part does the same check again for real, so
    this is only for telling the user early.
    """
    repository.validate_repo(repo)
    org = _org(repo, org)
    number = check_new_base(base) if base is not None else check_new_base(
        record_store.next_free_base(repo, org, config.get_start_number(repo)))
    chosen = check_variant(variant) if variant is not None else record_store.next_free_variant(repo, number, org)
    pn = PN(org, number, chosen)
    if not record_store.exists(repo, pn):
        return NumberCheck(pn)
    try:
        record = record_store.load(repo, pn)
    except record_model.RegistryError:
        return NumberCheck(pn, True, "(its record can't be read)", "")
    return NumberCheck(pn, True, record.name, record.status)


@_friendly
def suggest_variant_number(repo, base, org=None):
    """The variant number New Part would use right now for this part number."""
    repository.validate_repo(repo)
    return record_store.next_free_variant(repo, check_base(base), _org(repo, org))


@_friendly
def list_variants(repo, base, org=None):
    """The records of every variant of a part number, in order (for showing what already exists)."""
    repository.validate_repo(repo)
    return record_store.load_variants(repo, check_base(base), _org(repo, org))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: create part numbers")
    parser.add_argument("repo", help="path to the vault folder")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("part", help="create a new part number")
    p.add_argument("name")
    p.add_argument("--description", default="", help="optional extra context or tags")
    p.add_argument("--number", type=int, help="ask for this part number instead of the next free one")
    p.add_argument("--variant", type=int, help="ask for this variant number instead of the lowest free one")

    p = sub.add_parser("variant", help="create a new variant of an existing part number")
    p.add_argument("base", type=int, help="the existing part number, for example 42")
    p.add_argument("name")
    p.add_argument("--description", default="", help="optional extra context or tags")
    p.add_argument("--variant", type=int, help="ask for this variant number instead of the next free one")

    p = sub.add_parser("variants", help="list the variants of a part number")
    p.add_argument("base", type=int)

    sub.add_parser("next", help="show the next free part number")
    args = parser.parse_args(argv)

    try:
        if args.command == "part":
            print(f"Created {new_part(args.repo, args.name, args.description, base=args.number, variant=args.variant)}")
        elif args.command == "variant":
            print(f"Created {new_variant(args.repo, args.base, args.name, args.description, variant=args.variant)}")
        elif args.command == "variants":
            records = list_variants(args.repo, args.base)
            if not records:
                print(f"No variants of part number {format_base(args.base)} yet.")
            for r in records:
                print(f"{r.pn}  {r.status:<9} {r.name}")
            if records:
                print(f"Next free variant: {format_variant(suggest_variant_number(args.repo, args.base))}")
        else:
            print(f"Next free part number: {format_base(suggest_part_number(args.repo))}")
    except LitterboxError as e:
        print(f"\nERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())