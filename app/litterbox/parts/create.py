"""
create.py - New Part and New Variant: give a part its number by creating its record, committing and
pushing it. Once pushed, the number is yours for good.

If someone else takes the same number first, the push fails and Litterbox picks the next free one and tries
again (ATTEMPTS times). Creating many parts at once (the importer) is in create_batch.py.

New Part and New Assembly differ only in their variants: an assembly's start at the org's assembly_variant_start
(500 unless the org chose another), a part's stay below it. A variant typed by hand may be any free one.

A non-CAD part (noncad=True: paint, raw stock, a kit put together in its BOM) is created the same way. The first
one in a vault raises its min_litterbox_version to NONCAD_MIN_VERSION in the same commit, so an older Litterbox,
which would take it for a CAD part with no files yet, is told to update.

Projects (core/projects.py): New Part with a project takes a number in that project's block; with no project, it
never takes (or accepts) a number inside a block. Every record is given the project its number's block belongs to,
so a new variant of a project's part is in that project too.
"""

from functools import wraps
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox import version
from litterbox.core import numbering
from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.core.part_number import PN, PNError, check_new_base, check_org, check_variant, format_base, format_variant
from litterbox.errors import LitterboxError
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import permission_check
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config
from litterbox.vault import config_write


MAX_NAME = 100

MAX_DESCRIPTION = 500

ATTEMPTS = 5            # how many times to pick a number again if someone else got there first

NONCAD_MIN_VERSION = "0.5.1"    # the first Litterbox that knows non-CAD parts

ANY = "*any project*"   # new_part(project=ANY): a new variant, whose base decides its project

PART, ASSEMBLY = "part", "assembly"     # new_part(kind=...): which variants it takes


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


def project_name(projects, base):
    """The project a part number belongs to, by its block ("" for none): what its record says."""
    owner = project_rules.project_of(base, projects)
    return owner.name if owner else ""


def check_project_number(base, chosen, projects):
    """Refuse a part number typed for New Part that is in the wrong block: inside a project's block with no project
    chosen, or outside the chosen project's block."""
    owner = project_rules.project_of(base, projects)
    if chosen is None and owner is not None:
        raise CreateError(f"{format_base(base)} is in project {owner.describe()}. Choose {owner.name} in Project, "
                          "or use a part number outside every project.")
    if chosen is not None and owner != chosen:
        raise CreateError(f"{format_base(base)} isn't in project {chosen.describe()}: its part numbers start with "
                          f"{chosen.prefix}.")


def next_number(repo, org, chosen, projects):
    """The part number New Part takes when the box is left empty: the lowest free one in the chosen project's block,
    or, with no project, the next free one (from the start number) outside every block."""
    if chosen is None:
        return check_new_base(record_store.next_free_base(repo, org, config.get_start_number(repo),
                                                          project_rules.outside_blocks(projects)))
    low, high = chosen.block()
    try:
        return numbering.lowest_unused(record_store.used_bases(repo, org), low, high)
    except PNError:
        raise CreateError(f"Every part number in project {chosen.describe()} is used.") from None


def variant_range(repo, kind=PART):
    """(lowest, highest) variant New Part (kind=PART) or New Assembly (kind=ASSEMBLY) takes on its own."""
    if kind not in (PART, ASSEMBLY):
        raise CreateError(f"Unknown kind of part: {kind!r}.")
    start = config.get_assembly_variant_start(repo)
    return (start, part_number.MAX_VARIANT) if kind == ASSEMBLY else (part_number.MIN_VARIANT, start - 1)


def next_variant_number(repo, number, org, kind=PART):
    """The lowest free variant of a part number in the kind's range. Raises CreateError if they are all used."""
    low, high = variant_range(repo, kind)
    try:
        return record_store.next_free_variant(repo, number, org, low, high)
    except PNError:
        raise CreateError(f"Every {kind} variant of part number {format_base(number)} ({format_variant(low)} to "
                          f"{format_variant(high)}) is used.") from None


def chosen_project(repo, project):
    """(the Project chosen, every project): None for no project. Raises an error if there is no such project."""
    projects = config.get_projects(repo)
    return (project_rules.find(project, projects) if project else None), projects


def sync_vault(repo):
    """Download the latest records. Local edits to checked-out files are set aside and put back."""
    remote.sync(repo)


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


def undo_creation(repo, record_path, committed, config_rel=None):
    """Take back a creation that did not get pushed: our commit, and the file. Never raises.

    Only our one commit and our one new file are touched. Anything else in the
    folder, such as changes to parts you have checked out, is left alone.
    """
    try:
        if committed:
            runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
        runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--", record_path], repo)
        if config_rel:
            if repository.in_head(repo, config_rel):
                runner.run(["git", "restore", "--staged", "--worktree", "--", config_rel], repo, quiet=True)
            else:
                runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", "--", config_rel], repo, quiet=True)
                (Path(repo) / config_rel).unlink(missing_ok=True)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not fully undo the creation of {record_path}: {e}")
    try:
        read_only.delete_file(Path(repo) / record_path)
    except OSError as e:
        diagnostics.LOG(f"WARNING: could not delete {record_path}: {e}")


def _create(repo, name, description, org, choose, noncad=False):
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
        kind = record_model.KIND_NONCAD if noncad else record_model.KIND_CAD
        project = project_name(config.get_projects(repo), pn.base)
        permission_check.check_new_number(repo, project)       # a restricted project: its members only
        try:
            record_store.create_record(repo, pn, name, user, description=description, project=project, kind=kind)
        except record_model.PNExistsError:
            raise CreateError(f"{pn} already exists in your copy of the vault.") from None
        paths, config_rel = [record_path], None
        if noncad and _needs_newer(repo):
            config_rel = layout.CONFIG_PATH
            config_write.stamp(repo, NONCAD_MIN_VERSION)
            paths.append(config_rel)

        committed = False
        try:
            runner.run(["git", "add", "--", *paths], repo)
            runner.run(["git", "commit", "-m", f"{pn}: Created - {name}", "--", *paths], repo)
            committed = True
            runner.run(["git", "push"], repo)
        except LitterboxError as e:
            undo_creation(repo, record_path, committed, config_rel)
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
            undo_creation(repo, record_path, committed, config_rel)
            raise

        read_only.enforce_read_only(repo)          # the new record is read-only until someone checks it out
        return pn

    raise CreateError(f"Could not create a number after {ATTEMPTS} tries. The last error was:\n\n{last_error}")


def _needs_newer(repo):
    """True if the vault doesn't yet need a Litterbox that knows non-CAD parts."""
    wanted = config.load(repo).get("min_litterbox_version")
    try:
        return not wanted or version.parse(str(wanted)) < version.parse(NONCAD_MIN_VERSION)
    except ValueError:
        return True


@friendly
def new_part(repo, name, description="", base=None, variant=None, org=None, project=None, kind=PART, noncad=False):
    """Create a new part number and return the PN.

    Leave `base` empty to take the lowest unused part number, or give a number
    to ask for a particular one. `project` (a project's name) takes the number from that project's block (a
    `base` given must be in it); with no project, the number is never in a block. `project=ANY` is for a new
    variant: the base given decides the project. Leave `variant` empty to take the lowest unused
    variant of that part number in the kind's range (variant_range: 001 for a new part number, or 500 for a new
    assembly's), or give a number (1 to 999) to ask for that one. The part number does not have to
    exist yet: asking for 12345-501 is fine even if 12345-001 was never made.

    Numbers you ask for by name that are already taken give an error saying by what. noncad=True makes a non-CAD
    part (or assembly, with kind=ASSEMBLY).
    """
    manual_base = check_new_base(base) if base is not None else None
    manual_variant = check_variant(variant) if variant is not None else None

    def choose(org):
        number = manual_base
        if project is not ANY:                          # read again each time: the vault may have just changed
            chosen, projects = chosen_project(repo, project)
            if number is None:
                number = next_number(repo, org, chosen, projects)
            else:
                check_project_number(number, chosen, projects)
        elif number is None:
            raise CreateError("A new variant needs the part number it is a variant of.")
        if manual_variant is None:
            return PN(org, number, next_variant_number(repo, number, org, kind))
        if manual_variant in record_store.used_variants(repo, number, org):
            raise CreateError(
                f"{PN(org, number, manual_variant)} is already in use"
                f"{describe_number(repo, org, number, manual_variant)}. "
                "Pick a different variant number, or leave it blank for the next free one.")
        return PN(org, number, manual_variant)

    return _create(repo, name, description, org, choose, noncad)


def new_variant(repo, base, name, description="", variant=None, org=None, kind=PART, noncad=False):
    """Create a new variant of a part number. The same as new_part with a part number given; it is in the same
    project as the part number's other variants."""
    return new_part(repo, name, description, base=base, variant=variant, org=org, project=ANY, kind=kind,
                    noncad=noncad)
