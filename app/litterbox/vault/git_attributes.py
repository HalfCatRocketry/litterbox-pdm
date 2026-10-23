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
"""

import re
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
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
)


VERSION = 2

MIN_LITTERBOX = "0.5.1"         # the oldest Litterbox that knows every lockable rule in RULES

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


def needs_update(repo):
    """(the vault's block version or None, True if this Litterbox would change the block)."""
    if not is_litterbox_vault(repo):
        return None, False
    text = read(repo)
    found = vault_version(text)
    if found is not None and found > VERSION:
        return found, False                                 # a newer Litterbox wrote it: leave it alone
    return found, updated_text(text) != text.replace("\r\n", "\n")


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
    LFS rules now cover, raise min_litterbox_version if lockable rules were added, then commit and upload all of it
    together. If anything fails it is all put back. Returns the rules added ([] if there was nothing to do)."""
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
    if new_text == old_text.replace("\r\n", "\n"):
        return []
    added = added_rules(old_text, new_text)
    config_rel = layout.CONFIG_PATH
    config_before = config.config_path(repo).read_bytes()
    touched, committed = [FILE_NAME], False
    try:
        path.write_bytes(new_text.encode("utf-8"))
        if any(rule.endswith(" lockable") for rule in added):
            config_write.stamp(repo, min_version=MIN_LITTERBOX)
            if config.config_path(repo).read_bytes() != config_before:
                touched.append(config_rel)
        runner.run(["git", "add", "--", *touched], repo)
        converted = _pattern_files(repo, added)
        if converted:
            runner.run(["git", "add", "--renormalize", "--", *converted], repo)
            staged = runner.run(["git", "diff", "--cached", "--name-only", "-z"], repo, quiet=True)
            touched += [p for p in staged.split("\0") if p and p not in touched]
        message = f"Litterbox: file rules version {VERSION}" + (f" ({len(added)} rules added)" if added else "")
        runner.run(["git", "commit", "-m", message, "--", *touched], repo)
        committed = True
        guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            runner.run(["git", "reset", "-q", "--", *touched], repo, quiet=True)
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
            config.config_path(repo).write_bytes(config_before)   # converted files changed only in the index
        except (LitterboxError, OSError) as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {FILE_NAME}: {e}")
        raise
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

