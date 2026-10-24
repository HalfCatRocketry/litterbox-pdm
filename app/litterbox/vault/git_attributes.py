"""
git_attributes.py - the vault's .gitattributes: which files Git LFS stores and which can be locked. Litterbox owns
one block of the file, between two markers, and brings that block up to date when a newer Litterbox has more rules.

    # >>> Litterbox rules, version 1. Litterbox updates the lines down to '# <<< Litterbox'; don't edit them.
    *.[sS][lL][dD][pP][rR][tT] filter=lfs diff=lfs merge=lfs -text lockable
    ...
    # <<< Litterbox

Lines outside the block are the team's own and are never changed. Rules are only ever added or widened, never
removed: taking a Git LFS rule away from files already stored that way breaks every copy. Files already in the vault
that match a new Git LFS rule are converted in the same commit (git add --renormalize), without rewriting history.

Git follows the file as soon as it arrives, whichever Litterbox someone runs. A lockable file is read-only until it
is locked, so an update that adds lockable rules also raises min_litterbox_version to MIN_LITTERBOX: an older
Litterbox might not lock those files at Check Out, and they would stay read-only.

Vaults made before the markers existed (Litterbox 0.4.1 and older) have their rules under a plain header comment;
updated_text() recognises those (LEGACY_HEADERS, LEGACY_RULES) and puts them inside the markers.

    vault_version(text)   the block's version in a vault's file: None when it has no Litterbox rules at all, 0 for
                          the rules of Litterbox 0.4.1 and older
    needs_update(repo)    (the vault's version, True if this Litterbox has a newer block)
    updated_text(text)    the file with the block brought up to date
    update(repo)          do it: get the latest, rewrite the block, convert matching files, commit and upload

Version 4 (0.6.3) keeps cancelled revisions in cad/cancelled-revs (lockable, so read-only, like the rest of cad/),
and its update also moves a vault's old cancelled-revs/ folder there in the same commit (legacy_cancelled_files).
"""

import os
import re
import stat
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.git import sparse
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import team_permissions
from litterbox.vault import config
from litterbox.vault import config_write


FILE_NAME = ".gitattributes"

LFS = "filter=lfs diff=lfs merge=lfs -text"


def any_case(extension):
    """'step' -> '*.[sS][tT][eE][pP]': a pattern that matches the extension in any mix of capitals. Git and Git LFS
    only ignore case where the computer does (Windows), so the pattern itself has to."""
    return "*." + "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else c for c in extension)


# Files that belong to a part (they live in cad/ under its name and are checked out with it): SolidWorks files,
# the exports made from them, and other CAD formats.
LOCKABLE_EXTENSIONS = (
    "sldprt", "sldasm", "slddrw",                          # SolidWorks
    "step", "stp", "pdf",                                   # exports: STEP from the model, PDF from the drawing
    "iges", "igs", "x_t", "x_b", "sat", "stl", "3mf",       # other 3D exports
    "dxf", "dwg",                                           # 2D exports (flat patterns, laser and waterjet cutting)
    "eprt", "easm", "edrw",                                 # eDrawings
)


# Other binary files that may end up in a vault (pictures, office documents, archives, video, SolidWorks
# templates): stored with Git LFS so they don't bloat the history, but not locked.
LFS_EXTENSIONS = (
    "png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp", "heic",
    "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx",
    "zip", "7z", "rar",
    "mp4", "mov", "avi",
    "prtdot", "asmdot", "drwdot", "slddrt", "sldlfp", "sldblk",
)


# Version 2 (0.5.1): documents. Other files people keep as documents, stored with Git LFS wherever they are.
DOCUMENT_EXTENSIONS = (
    "odt", "ods", "odp", "odg", "rtf", "vsd", "vsdx", "mpp", "pub", "one",     # office documents
    "key", "pages", "numbers",                                                 # Apple's office documents
    "psd", "ai", "indd", "eps", "afdesign", "xcf",                             # design files
    "tar", "gz", "tgz", "bz2", "xz",                                           # more archives
    "mp3", "wav", "m4a", "mkv", "wmv", "webm", "m4v",                          # audio and video
)


# The block's rules. Add to the end (never remove or narrow a rule), and raise VERSION when you do.
RULES = (
    [f"{any_case(ext)} {LFS} lockable" for ext in LOCKABLE_EXTENSIONS]
    + [f"{any_case(ext)} {LFS}" for ext in LFS_EXTENSIONS]
    + [
        f"cad/** {LFS} lockable",                           # anything else in cad/ belongs to a part too
        "PN-logs/*.yaml lockable",
        f"cancelled-revs/** {LFS}",
    ]
    + [                                                     # version 2
        f"documents/** {LFS} lockable",                     # every file of a document, whatever its type
        "DOC-logs/*.yaml lockable",
    ]
    + [f"{any_case(ext)} {LFS}" for ext in DOCUMENT_EXTENSIONS]
    + [                                                     # version 3 (0.6.0): the team's Toolbox
        f"toolbox/** {LFS} lockable",                       # read-only for everyone; only Admins upload it
    ]
    + [                                                     # version 4 (0.6.3): cancelled revisions under cad/
        f"{layout.CANCELLED_DIR_NAME}/** {LFS} lockable",   # read-only: kept only for the history
    ]
)


VERSION = 4

MIN_LITTERBOX = "0.6.3"         # the oldest Litterbox that knows every lockable rule in RULES (and keeps cancelled
                                # revisions in cad/cancelled-revs)

BEGIN = "# >>> Litterbox rules, version {version}. Litterbox updates the lines down to '# <<< Litterbox'; don't " \
        "edit them."
END = "# <<< Litterbox"
BEGIN_PATTERN = re.compile(r"^# >>> Litterbox rules, version (\d+)\b")

# What Litterbox 0.4.1 and older wrote, without markers: a header comment, then its rules.
LEGACY_HEADERS = (
    "# Litterbox: CAD files are stored with Git LFS and can be locked (checked out).",
    "# Litterbox: CAD files, their exports and other binary files are stored with Git LFS; a part's files can be "
    "locked (checked out). Patterns match any capitals.",
)
LEGACY_RULES = frozenset(
    [f"*.{ext} {LFS} lockable" for ext in ("SLDPRT", "SLDASM", "SLDDRW")]
    + ["PN-logs/*.yaml lockable", f"cancelled-revs/** {LFS}"]
    + RULES                                                 # version 1's rules are 0.4.0's, without the markers
)


def block_lines(number=VERSION):
    return [BEGIN.format(version=number), *RULES, END]


def _find_block(lines):
    """(start, end) line indexes of the marked block (end is the END line), or None. Raises LitterboxError if the
    start marker has no end marker, since then nobody can tell where the team's own lines begin."""
    for start, line in enumerate(lines):
        if BEGIN_PATTERN.match(line.strip()):
            for end in range(start + 1, len(lines)):
                if lines[end].strip() == END:
                    return start, end
            raise LitterboxError(f"{FILE_NAME} has the start of the Litterbox rules but not their end "
                                 f"('{END}'). Put that line back after the rules, then try again.")
    return None


def _find_legacy(lines):
    """(start, end) of an unmarked block from Litterbox 0.4.1 or older: its header and the rules right under it."""
    for start, line in enumerate(lines):
        if line.strip() in LEGACY_HEADERS:
            end = start
            while end + 1 < len(lines) and lines[end + 1].strip() in LEGACY_RULES:
                end += 1
            return start, end
    return None


def vault_version(text):
    """The block's version in this file's text: None when it has no Litterbox rules, 0 for 0.4.1 and older."""
    lines = (text or "").splitlines()
    for line in lines:
        found = BEGIN_PATTERN.match(line.strip())
        if found:
            return int(found.group(1))
    return 0 if _find_legacy(lines) else None


def updated_text(text):
    """The file with Litterbox's block brought up to date. The team's own lines stay as they are."""
    lines = (text or "").replace("\r\n", "\n").splitlines()
    span = _find_block(lines) or _find_legacy(lines)
    if span is not None:
        start, end = span
        lines[start:end + 1] = block_lines()
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines += block_lines()
    return "\n".join(lines) + "\n"


def rules_in(text):
    """The rules (not comments or blank lines) a .gitattributes text has."""
    return {line.strip() for line in (text or "").splitlines() if line.strip() and not line.lstrip().startswith("#")}


def added_rules(old_text, new_text):
    """The rules the new text has that the old one didn't, in the new text's order."""
    before = rules_in(old_text)
    return [line.strip() for line in new_text.splitlines() if line.strip() in rules_in(new_text) - before]


def read(repo):
    path = Path(repo) / FILE_NAME
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def is_litterbox_vault(repo):
    """Litterbox set this vault up (it has its settings file). Other repositories are left alone."""
    return config.config_path(repo).is_file()


def legacy_cancelled_files(repo):
    """The files the vault keeps in the old cancelled-revs/ folder (before 0.6.3), which the update moves. Asks git
    only when the folder is there (or a hidden project may have left it out of this copy), since this runs at every
    refresh; [] if it can't be told."""
    try:
        if not (Path(repo) / layout.LEGACY_CANCELLED_DIR_NAME).is_dir() and not sparse.excluded(repo):
            return []
        return repository.tracked(repo, f"{layout.LEGACY_CANCELLED_DIR_NAME}/")
    except (LitterboxError, OSError):
        return []


def moved_path(rel):
    """Where a file of the old cancelled-revs/ folder goes: "cad/cancelled-revs/CANCELLED_..."."""
    return f"{layout.CANCELLED_DIR_NAME}/{rel.split('/', 1)[1]}"


def needs_update(repo):
    """(the vault's block version or None, True if this Litterbox would change the block, or has cancelled
    revisions to move)."""
    if not is_litterbox_vault(repo):
        return None, False
    text = read(repo)
    found = vault_version(text)
    if found is not None and found > VERSION:
        return found, False                                 # a newer Litterbox wrote it: leave it alone
    return found, updated_text(text) != text.replace("\r\n", "\n") or bool(legacy_cancelled_files(repo))


def _pattern_files(repo, rules):
    """Files git tracks that these rules' patterns match (the ones a new Git LFS rule may convert)."""
    patterns = [rule.split()[0] for rule in rules if "filter=lfs" in rule]
    if not patterns:
        return []
    found = runner.run(["git", "ls-files", "-z", "--", *patterns], repo, quiet=True)
    return [p for p in found.split("\0") if p]


@converts_errors
def update(repo):
    """Bring the vault's Litterbox rules up to date: get the latest, rewrite the block, convert files that new Git
    LFS rules now cover, raise min_litterbox_version if lockable rules were added, move the old cancelled-revs/
    folder into cad/, then commit and upload all of it together. If anything fails it is all put back. Returns the
    rules added ([] if there was nothing to do)."""
    repository.validate_repo(repo)
    team_permissions.require(repo, "manage_settings")
    repo = Path(repo)
    remote.pull(repo)
    path = repo / FILE_NAME
    before = path.read_bytes() if path.is_file() else None
    old_text = before.decode("utf-8", errors="replace") if before is not None else ""
    if (vault_version(old_text) or 0) > VERSION:
        raise LitterboxError(f"This vault's {FILE_NAME} was written by a newer Litterbox. Update Litterbox first.")
    new_text = updated_text(old_text)
    legacy = legacy_cancelled_files(repo)
    if new_text == old_text.replace("\r\n", "\n") and not legacy:
        return []
    added = added_rules(old_text, new_text)
    moved = []
    config_rel = layout.CONFIG_PATH
    config_before = config.config_path(repo).read_bytes()
    touched, committed = [FILE_NAME], False
    try:
        path.write_bytes(new_text.encode("utf-8"))
        if any(rule.endswith(" lockable") for rule in added) or legacy:
            config_write.stamp(repo, min_version=MIN_LITTERBOX)
            if config.config_path(repo).read_bytes() != config_before:
                touched.append(config_rel)
        runner.run(["git", "add", "--", *touched], repo)
        for rel in legacy:                                  # into cad/cancelled-revs, kept with their history
            target = repo / moved_path(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            runner.run(["git", "mv", "--", rel, moved_path(rel)], repo)
            moved.append(rel)
        touched += [p for rel in moved for p in (rel, moved_path(rel))]
        converted = _pattern_files(repo, added)
        if converted:
            runner.run(["git", "add", "--renormalize", "--", *converted], repo)
            staged = runner.run(["git", "diff", "--cached", "--name-only", "-z"], repo, quiet=True)
            touched += [p for p in staged.split("\0") if p and p not in touched]
        message = f"Litterbox: file rules version {VERSION}" + (f" ({len(added)} rules added)" if added else "") \
            + (f", {len(moved)} cancelled files moved to {layout.CANCELLED_DIR_NAME}" if moved else "")
        runner.run(["git", "commit", "-m", message, "--", *touched], repo)
        committed = True
        guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            runner.run(["git", "reset", "-q", "--", *touched], repo, quiet=True)
            for rel in moved:                               # the moved files go back where they were
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                os.chmod(repo / moved_path(rel), stat.S_IREAD | stat.S_IWRITE)
                (repo / moved_path(rel)).replace(repo / rel)
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
            config.config_path(repo).write_bytes(config_before)   # converted files changed only in the index
        except (LitterboxError, OSError) as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {FILE_NAME}: {e}")
        raise
    if moved:
        try:
            (repo / layout.LEGACY_CANCELLED_DIR_NAME).rmdir()   # git leaves the emptied folder; only if it is empty
        except OSError:
            pass
    diagnostics.LOG(f"Updated the vault's {FILE_NAME} to Litterbox rules version {VERSION}"
                    + (f"; Litterbox {MIN_LITTERBOX} or newer is now needed." if config_rel in touched else "."))
    return added


def change_lines(old_text, new_text, limit=12):
    """What an update would add, for the question before it: one line per rule, cut short after `limit`."""
    added = added_rules(old_text, new_text)
    lines = [f"  {rule}" for rule in added[:limit]]
    if len(added) > limit:
        lines.append(f"  ...and {len(added) - limit} more")
    return lines

