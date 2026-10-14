"""
create.py - New Part and New Variant: give a part its number by creating its record, committing and
pushing it. Once pushed, the number is yours for good.

If someone else takes the same number first, the push fails and Litterbox picks the next free one and tries
again (ATTEMPTS times). Creating many parts at once (the importer) is in create_batch.py.
"""

import os
from functools import wraps
from pathlib import Path

from litterbox import diagnostics
from litterbox.core.part_number import PN, PNError, check_new_base, check_org, check_variant
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config


MAX_NAME = 100


MAX_DESCRIPTION = 500


ATTEMPTS = 5            # how many times to pick a number again if someone else got there first


class CreateError(LitterboxError):
    """A part number could not be created. The message is safe to show to a user."""


def friendly(func):
    """Make every public function raise only LitterboxError (CreateError is one)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (record_model.RegistryError, config.ConfigError, PNError) as e:
            raise CreateError(str(e)) from e
    return wrapper


def _clean_text(text, label, limit, required):
    text = " ".join(str(text or "").split())          # one line, single spaces
    if not text and required:
        raise CreateError(f"A {label} is required.")
    if len(text) > limit:
        raise CreateError(f"Keep the {label} under {limit} characters (it is {len(text)}).")
    return text


def clean_name(text):
    return _clean_text(text, "name", MAX_NAME, required=True)


def clean_description(text):
    return _clean_text(text, "description", MAX_DESCRIPTION, required=False)


def resolve_org(repo, org):
    return check_org(org) if org else config.get_org(repo)


def sync_vault(repo):
    """Download the latest records. Local edits to checked-out files are set aside and put back."""
    runner.run(["git", "pull", "--rebase", "--autostash"], repo)


def describe_number(repo, org, base, variant=None):
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


def _create(repo, name, description, org, choose):
    """Create, commit and push one record. `choose(org)` returns the PN to try.

    choose() is called again after every rejected push, so it always works from
    the newest records. It raises CreateError if a number typed in by hand is taken.
    """
    repository.validate_repo(repo)
    name = clean_name(name)
    description = clean_description(description)
    user = repository.get_user(repo)
    permission_check.check_permission(repo, user, "create")
    try:
        sync_vault(repo)
    except LitterboxError as e:
        raise CreateError(f"Could not get the latest records from the vault, so nothing was created. "
                           f"Are you online?\n\n{e}") from e
    org = resolve_org(repo, org)

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
                sync_vault(repo)
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


@friendly
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
                f"{describe_number(repo, org, number, manual_variant)}. "
                "Pick a different variant number, or leave it blank for the next free one.")
        return PN(org, number, manual_variant)

    return _create(repo, name, description, org, choose)


def new_variant(repo, base, name, description="", variant=None, org=None):
    """Create a new variant of a part number. The same as new_part with a part number given."""
    return new_part(repo, name, description, base=base, variant=variant, org=org)
