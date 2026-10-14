"""
init_vault.py - set up a brand-new vault.

A vault is a Git repository that Litterbox manages. This file takes an EMPTY repository (made on your Git host
and cloned to your computer) and turns it into a Litterbox vault:

    .gitattributes         CAD files go through Git LFS and can be locked (that is what "check out" is)
    .gitignore             keeps temporary and lock files out of the vault
    .litterbox/config.yaml the vault's shared settings: org code, first part number, digits, format version
    README.md              a short note for anyone who stumbles on the repository (only if there is none)

...commits them, pushes them, and (optionally) sets up the team with you as its Owner.

    python init_vault.py <folder> --org HCR [--start 10001] [--base-digits 5] [--variant-digits 3]
                         [--no-team] [--no-push] [--name "Your Name"] [--email you@example.com]

The folder must be a clone of an empty (or almost empty) repository. Nothing in it is overwritten: an existing
.gitattributes or .gitignore only gets the lines it is missing. If any step fails, the files this wrote are
removed again and any commit is undone, so you can simply run it again.

    plan(...)   checks everything and returns the problems and warnings, without touching anything
    create(...) does it (calls plan() first and refuses if there are problems)

CHOOSING THE NUMBERS (they can't be changed once the first part number exists)
    digits in the part number   5 (default) allows 99,999 parts; 4 allows 9,999; 6 allows 999,999.
    digits in the variant       3 (default) allows 999 variants of one part number.
    first part number           the first number handed out; leave at 1 unless you want to start higher (10001...). Numbers count up
                                from there, then loop round to 1 and up to just below it, so every number gets used.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from litterbox.vault import config
from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox.core import pn as pn_module
from litterbox import version
from litterbox.core.pn import PNError, check_org

GITATTRIBUTES = ".gitattributes"
GITIGNORE = ".gitignore"
README = "README.md"

LFS = "filter=lfs diff=lfs merge=lfs -text"
ATTRIBUTE_LINES = [
    f"*.SLDPRT {LFS} lockable",
    f"*.SLDASM {LFS} lockable",
    f"*.SLDDRW {LFS} lockable",
    "PN-logs/*.yaml lockable",
    f"cancelled-revs/** {LFS}",
]
ATTRIBUTE_HEADER = "# Litterbox: CAD files are stored with Git LFS and can be locked (checked out)."

IGNORE_LINES = [
    ".tmp-*",             # half-written files Litterbox keeps while saving
    "~$*",                # SolidWorks / Office lock files
    "*.bak",
    "Thumbs.db",
]
IGNORE_HEADER = "# Litterbox: temporary and lock files."

README_TEXT = """# {org} vault

This repository is managed by [Litterbox](https://github.com/HalfCatRocketry/litterbox-pdm), a lightweight
product data manager. Parts are checked out and in with the Litterbox app, not with Git commands.

- `cad/` holds the CAD files.
- `PN-logs/` holds one record per part number.
- `.litterbox/` holds the team's shared settings.

Please don't rename, move or delete files here by hand.
"""

EXISTING_VAULT_FOLDERS = ("cad", "PN-logs", ".litterbox")


class InitError(eng.LitterboxError):
    """Setting up the vault failed. The message is safe to show to a user."""


@dataclass
class InitPlan:
    org: str = ""
    problems: list = field(default_factory=list)       # reasons it can't go ahead
    warnings: list = field(default_factory=list)       # worth knowing; the user decides

    @property
    def ok(self):
        return not self.problems


@dataclass
class InitResult:
    org: str
    files: list                      # what was written (repo-relative)
    pushed: bool
    warnings: list
    owner: object = None             # the people.Person set up as Owner, if the team was set up
    team_error: str = ""             # why the team wasn't set up (the vault is fine; use Team... later)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def numbering_warnings(start_number, base_digits, variant_digits):
    """Things worth a second thought about the part-number format. Returns a list of sentences."""
    warnings = []
    room = 10 ** base_digits - 1          # the numbers loop round past the highest, so the start number doesn't matter
    if base_digits < 4:
        warnings.append(f"{base_digits} digit{'s' if base_digits != 1 else ''} in the part number leaves room for "
                        f"only {room:,} parts. That can't be changed later.")
    if base_digits > 7:
        warnings.append(f"{base_digits} digits makes long part numbers and file names, and Windows limits full "
                        "paths to about 260 characters.")
    if variant_digits < 2:
        warnings.append(f"{variant_digits} digit in the variant allows only {10 ** variant_digits - 1} variants of "
                        "one part number. That can't be changed later.")
    return warnings


def _git(repo, *args, quiet=True):
    return eng.run(["git", *args], repo, quiet=quiet)


def _has_commits(repo):
    try:
        _git(repo, "rev-parse", "--verify", "-q", "HEAD")
        return True
    except eng.LitterboxError:
        return False


def plan(folder, org, start_number=1, base_digits=pn_module.DEFAULT_BASE_DIGITS,
         variant_digits=pn_module.DEFAULT_VARIANT_DIGITS, push=True):
    """Check that `folder` can become a vault with these settings. Changes nothing."""
    result = InitPlan()
    try:
        result.org = check_org(str(org).strip()).upper()
    except PNError as e:
        result.problems.append(str(e))

    for label, value, (low, high) in (("The number of digits in the part number", base_digits, pn_module.BASE_DIGITS_RANGE),
                                      ("The number of digits in the variant", variant_digits, pn_module.VARIANT_DIGITS_RANGE)):
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            result.problems.append(f"{label} must be a whole number from {low} to {high}.")
    if isinstance(start_number, bool) or not isinstance(start_number, int) or start_number < 1:
        result.problems.append("The first part number must be a whole number, 1 or higher.")
    elif not result.problems and start_number > 10 ** base_digits - 1:
        result.problems.append(f"The first part number {start_number} doesn't fit in {base_digits} digits.")
    if not result.problems:
        result.warnings.extend(numbering_warnings(start_number, base_digits, variant_digits))

    folder = Path(folder)
    if not folder.is_dir():
        result.problems.append(f"The folder doesn't exist: {folder}")
        return result
    try:
        prefix = _git(folder, "rev-parse", "--show-prefix")
    except eng.LitterboxError:
        result.problems.append(
            f"{folder} isn't a Git repository. Create an empty repository on your Git host, clone it to this "
            "computer, and choose the cloned folder.")
        return result
    if prefix:
        result.problems.append(f"{folder} is a folder inside a Git repository, not the top of one. Choose the "
                               "folder you cloned.")
        return result

    try:
        eng.run(["git", "lfs", "version"], folder, quiet=True)
    except eng.LitterboxError:
        result.problems.append("Git LFS isn't installed. It comes with Git for Windows: reinstall Git for "
                               "Windows, or install Git LFS from git-lfs.com.")

    for key, what in (("user.name", "name"), ("user.email", "email address")):
        try:
            value = _git(folder, "config", key)
        except eng.LitterboxError:
            value = ""
        if not value:
            result.problems.append(f"Git doesn't know your {what} yet. Run this once, then try again:\n"
                                   f'  git config --global {key} "..."')

    present = [name for name in EXISTING_VAULT_FOLDERS if (folder / name).exists()]
    if present:
        result.problems.append("This already looks like a vault (it has " + ", ".join(present) + "). "
                               "Choose an empty repository, or use Add org... for an existing vault.")

    if push:
        remotes = _git(folder, "remote").split()
        if "origin" not in remotes:
            result.problems.append("The repository has no remote called 'origin', so there is nowhere to upload "
                                   "the vault. Clone the empty repository from your Git host.")
    return result


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _merge_lines(path, lines, header):
    """Make sure `path` contains each of `lines`, adding only what's missing and never changing what's there.
    Returns the file's original bytes (None if it didn't exist) and whether anything was written."""
    original = path.read_bytes() if path.is_file() else None
    text = original.decode("utf-8", errors="replace") if original is not None else ""
    have = {line.strip() for line in text.splitlines()}
    missing = [line for line in lines if line not in have]
    if not missing and original is not None:
        return original, False
    out = text
    if out and not out.endswith("\n"):
        out += "\n"
    if out:
        out += "\n"
    out += header + "\n" + "\n".join(missing) + "\n"
    path.write_bytes(out.replace("\r\n", "\n").encode("utf-8"))
    return original, True


class _Writer:
    """Writes the vault's files and can put everything back exactly as it was."""

    def __init__(self, repo):
        self.repo = Path(repo)
        self.created = []                       # repo-relative paths that didn't exist before
        self.modified = {}                      # repo-relative path -> original bytes
        self.made_folders = []
        self.old_head = None
        self.committed = False

    def note(self, rel, original):
        if original is None:
            if rel not in self.created:
                self.created.append(rel)
        elif rel not in self.modified:
            self.modified[rel] = original

    @property
    def paths(self):
        return self.created + list(self.modified)

    def undo(self):
        repo = self.repo
        try:
            if self.committed:
                if self.old_head:
                    eng.run(["git", "reset", "--soft", self.old_head], repo, quiet=True)
                else:
                    eng.run(["git", "update-ref", "-d", "HEAD"], repo, quiet=True)
            for rel in self.created:
                eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "-q", "--", rel], repo, quiet=True)
                try:
                    (repo / rel).unlink()
                except OSError:
                    pass
            for rel, original in self.modified.items():
                (repo / rel).write_bytes(original)
                if self.old_head:
                    eng.run(["git", "reset", "-q", "HEAD", "--", rel], repo, quiet=True)
                else:
                    eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "-q", "--", rel], repo, quiet=True)
            for folder in self.made_folders:
                try:
                    (repo / folder).rmdir()
                except OSError:
                    pass
        except eng.LitterboxError as e:
            eng.LOG(f"WARNING: could not fully undo the vault set-up: {e}")


def create(folder, org, start_number=1, base_digits=pn_module.DEFAULT_BASE_DIGITS,
           variant_digits=pn_module.DEFAULT_VARIANT_DIGITS, push=True, set_up_team=True, name=None, email=None,
           min_version=version.VERSION):
    """Turn the empty cloned repository in `folder` into a Litterbox vault. Returns an InitResult.

    Raises InitError if there are problems (nothing is changed), or if a step fails (everything is undone)."""
    checked = plan(folder, org, start_number, base_digits, variant_digits, push)
    if not checked.ok:
        raise InitError("The vault can't be set up yet:\n- " + "\n- ".join(checked.problems))
    org = checked.org
    repo = Path(folder)
    writer = _Writer(repo)
    warnings = list(checked.warnings)
    writer.old_head = _git(repo, "rev-parse", "HEAD") if _has_commits(repo) else None

    try:
        try:                                                # makes sure the upload hooks are in this repository
            eng.run(["git", "lfs", "install", "--local"], repo, quiet=True)
        except eng.LitterboxError as e:
            warnings.append(f"Could not switch on Git LFS for this repository ({e}). If uploads fail, run "
                            "'git lfs install' once.")

        original, changed = _merge_lines(repo / GITATTRIBUTES, ATTRIBUTE_LINES, ATTRIBUTE_HEADER)
        if changed:
            writer.note(GITATTRIBUTES, original)
        original, changed = _merge_lines(repo / GITIGNORE, IGNORE_LINES, IGNORE_HEADER)
        if changed:
            writer.note(GITIGNORE, original)
        if not (repo / README).exists():
            (repo / README).write_text(README_TEXT.format(org=org), encoding="utf-8", newline="\n")
            writer.note(README, None)

        if not (repo / config.CONFIG_DIR).exists():
            writer.made_folders.append(config.CONFIG_DIR)
        config_rel = f"{config.CONFIG_DIR}/{config.CONFIG_FILE}"
        writer.note(config_rel, None)
        config.save(repo, org=org, start_number=start_number, base_digits=base_digits,
                    variant_digits=variant_digits)
        config.stamp(repo, min_version=min_version)

        paths = writer.paths
        eng.run(["git", "add", "--"] + paths, repo)
        eng.run(["git", "commit", "-m", f"Litterbox: set up the {org} vault", "--"] + paths, repo)
        writer.committed = True
        if push:
            eng.run(["git", "push", "-u", "origin", "HEAD"], repo)
    except BaseException:
        writer.undo()
        raise

    config.apply(repo)                                      # the rest of the program now knows the digit counts

    result = InitResult(org=org, files=paths, pushed=push, warnings=warnings)
    if push:
        try:
            eng.run(["git", "lfs", "locks"], repo, quiet=True)
        except eng.LitterboxError as e:
            warnings.append("The host did not answer a request about file locks. Check that Git LFS and file "
                            f"locking are available on this repository.\n{e}")
    if set_up_team and push:
        try:
            result.owner = people.setup_team(repo, name=name, email=email)
        except eng.LitterboxError as e:
            result.team_error = str(e)
    return result


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Turn an empty cloned repository into a Litterbox vault.")
    parser.add_argument("folder", help="the cloned, empty repository")
    parser.add_argument("--org", required=True, help="org code, 2 to 4 letters (HCR)")
    parser.add_argument("--start", type=int, default=1, help="first part number to hand out (default 1)")
    parser.add_argument("--base-digits", type=int, default=pn_module.NEW_VAULT_BASE_DIGITS)
    parser.add_argument("--variant-digits", type=int, default=pn_module.DEFAULT_VARIANT_DIGITS)
    parser.add_argument("--no-push", action="store_true", help="commit locally only")
    parser.add_argument("--no-team", action="store_true", help="don't set up the team (do it later in Team...)")
    parser.add_argument("--name", help="your name for the team list (default: git's user.name)")
    parser.add_argument("--email", help="your email for the team list (default: git's user.email)")
    parser.add_argument("--yes", action="store_true", help="go ahead even when there are warnings")
    args = parser.parse_args(argv)
    eng.LOG = print

    checked = plan(args.folder, args.org, args.start, args.base_digits, args.variant_digits, not args.no_push)
    if not checked.ok:
        print("The vault can't be set up yet:")
        for problem in checked.problems:
            print(f"- {problem}")
        return 1
    for warning in checked.warnings:
        print(f"WARNING: {warning}")
    if checked.warnings and not args.yes:
        if input("Go ahead anyway? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            return 1
    try:
        result = create(args.folder, args.org, args.start, args.base_digits, args.variant_digits,
                        push=not args.no_push, set_up_team=not args.no_team, name=args.name, email=args.email)
    except eng.LitterboxError as e:
        print(f"Failed. Nothing was left behind.\n{e}")
        return 1
    print(f"\nThe {result.org} vault is set up" + (" and uploaded." if result.pushed else " (not uploaded)."))
    if result.owner:
        print(f"{result.owner.name} is the Owner.")
    elif result.team_error:
        print(f"The team was not set up: {result.team_error}\nYou can do it later with Team... in Litterbox.")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
