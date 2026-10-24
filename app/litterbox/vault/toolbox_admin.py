"""
toolbox_admin.py - the team's SolidWorks Toolbox, kept in the vault's toolbox/ folder (layout.TOOLBOX_DIR_NAME) for
the Toolbox rule TEAM (core/toolbox_rules.py). Team > Toolbox... shows it (status) and, for an Admin or the Owner
(the permission "manage_toolbox"), changes it:

    copy_in(repo, folder)   make the team's Toolbox a copy of a Toolbox folder (C:\\SOLIDWORKS Data), and upload it
    open_for_changes(repo)  make its files writable on this computer, so SolidWorks can add sizes or settings
    upload(repo)            upload every change in the folder (new, changed and removed files) in one commit
    download(repo)          download every file of it (with download on demand, its files start as pointers)

Everyone else only reads it: its files are stored with Git LFS and lockable, so they are read-only
(vault/git_attributes.py, version 3, and git/read_only.enforce_read_only), and Litterbox refuses to upload anyone
else's change to it (team/guarded_push.toolbox_allowed). As everywhere in Litterbox, that is process control:
someone using git by hand could still change it.
"""

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.cad import cad_programs
from litterbox.core import toolbox_rules
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import team_permissions
from litterbox.vault import config

PERMISSION = "manage_toolbox"
FOLDER = layout.TOOLBOX_DIR_NAME


@dataclass
class Status:
    """What Team > Toolbox... shows."""
    rule: str = toolbox_rules.OFF                   # the vault's Toolbox rule
    folder: str = ""                                # the team's Toolbox on this computer
    files: int = 0                                  # files the vault has in it
    not_downloaded: int = 0                         # of those, how many are only pointers here
    changes: dict = field(default_factory=dict)     # {"added": [rel], "changed": [rel], "removed": [rel]}: not uploaded
    solidworks_folder: str = ""                     # the Toolbox this computer's SolidWorks uses ("" if unknown)
    solidworks_uses_it: bool = False                # ... and whether it is the team's

    @property
    def has_changes(self):
        return any(self.changes.values())


def folder_path(repo):
    return Path(repo) / FOLDER


def same_folder(a, b):
    """True if two folder paths are the same folder (any case, any slashes, with or without a last slash)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(str(a))).rstrip("\\/") == os.path.normcase(os.path.abspath(str(b))).rstrip("\\/")


def tracked(repo):
    """The team's Toolbox files git has (relative to the vault)."""
    return repository.tracked(repo, FOLDER)


def changes(repo):
    """{"added", "changed", "removed": [rel]}: what is different in the folder from what the vault has."""
    found = {"added": [], "changed": [], "removed": []}
    try:
        compared = runner.run(["git", "diff", "--name-status", "--no-renames", "-z", "HEAD", "--", FOLDER], repo,
                              quiet=True)
        new = runner.run(["git", "ls-files", "--others", "--exclude-standard", "-z", "--", FOLDER], repo, quiet=True)
    except LitterboxError:
        return found
    fields = [f for f in compared.split("\0") if f]
    for code, rel in zip(fields[::2], fields[1::2]):        # "M", path, "D", path, ...
        kind = {"A": "added", "D": "removed"}.get(code.strip()[:1], "changed")
        found[kind].append(rel)
    found["added"] += [rel for rel in new.split("\0") if rel]
    return found


def status(repo):
    """The team's Toolbox as this computer has it (Status). Never asks the server."""
    files = tracked(repo)
    folder = str(folder_path(repo))
    theirs = cad_programs.DEFAULT.library_folder()
    return Status(rule=config.get_toolbox_rule(repo), folder=folder, files=len(files),
                  not_downloaded=len(lfs_download.stubs(repo, files)), changes=changes(repo),
                  solidworks_folder=theirs, solidworks_uses_it=same_folder(theirs, folder))


def looks_like_toolbox(folder):
    """True if a folder is a SolidWorks Toolbox folder (C:\\SOLIDWORKS Data): it has the 'browser' folder of parts."""
    return (Path(folder) / "browser").is_dir()


def _overlap(a, b):
    """True if one folder is the other or inside it."""
    a, b = (os.path.normcase(os.path.abspath(str(p))).rstrip("\\/") + os.sep for p in (a, b))
    return a.startswith(b) or b.startswith(a)


def _writable(path):
    try:
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWUSR)
    except OSError:
        pass


@converts_errors
def open_for_changes(repo):
    """Make the team's Toolbox files writable on this computer (an Admin only), so SolidWorks can change them.
    Returns how many files. Upload makes them read-only again."""
    team_permissions.require(repo, PERMISSION)
    count = 0
    for folder, _dirs, files in os.walk(folder_path(repo)):
        for name in files:
            _writable(Path(folder) / name)
            count += 1
    return count


@converts_errors
def copy_in(repo, source, log=diagnostics.LOG):
    """Make the team's Toolbox a copy of the Toolbox folder `source` and upload it (an Admin only): files it has are
    copied in, and files the team's has that it doesn't are removed. Returns upload()'s counts."""
    team_permissions.require(repo, PERMISSION)
    source = Path(source)
    target = folder_path(repo)
    if not looks_like_toolbox(source):
        raise LitterboxError(f"{source} doesn't look like a SolidWorks Toolbox folder: it has no 'browser' folder. "
                             "Choose the folder Toolbox keeps its parts in (C:\\SOLIDWORKS Data, say).")
    if _overlap(source, repo):
        raise LitterboxError("Choose a Toolbox folder outside the vault to copy in.")
    remote.pull(repo)
    wanted = set()
    for folder, _dirs, files in os.walk(source):
        for name in files:
            src = Path(folder) / name
            rel = src.relative_to(source)
            wanted.add(str(rel).lower())
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                _writable(dst)
            shutil.copyfile(src, dst)
    for folder, _dirs, files in os.walk(target):
        for name in files:
            path = Path(folder) / name
            if str(path.relative_to(target)).lower() not in wanted:
                _writable(path)
                path.unlink()
    log(f"Copied {len(wanted)} file{'' if len(wanted) == 1 else 's'} of {source} into the team's Toolbox.")
    return upload(repo, pull=False)


@converts_errors
def upload(repo, pull=True):
    """Upload every change in the team's Toolbox folder in one commit (an Admin only), then make its files read-only
    again. Returns {"added": n, "changed": n, "removed": n}; all 0 if there was nothing to upload."""
    team_permissions.require(repo, PERMISSION)
    if pull:
        remote.pull(repo)
    found = changes(repo)
    counts = {kind: len(rels) for kind, rels in found.items()}
    if not any(counts.values()):
        read_only.enforce_read_only(repo)
        return counts
    committed = False
    try:
        runner.run(["git", "add", "-A", "--", FOLDER], repo)
        runner.run(["git", "commit", "-m", "Toolbox: " + summary(counts), "--", FOLDER], repo)
        committed = True
        guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            runner.run(["git", "reset", "-q", "--", FOLDER], repo)         # unstaged again: the files stay as they are
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not fully undo the Toolbox upload: {e}")
        raise
    read_only.enforce_read_only(repo)
    return counts


def summary(counts):
    """'12 files added, 1 changed' for an upload's counts."""
    parts = []
    for kind in ("added", "changed", "removed"):
        n = counts.get(kind, 0)
        if n:
            parts.append(f"{n} {'file' if n == 1 else 'files'} {kind}" if not parts else f"{n} {kind}")
    return ", ".join(parts) if parts else "no changes"


@converts_errors
def download(repo):
    """Download every file of the team's Toolbox that is only a pointer here. Returns how many were downloaded."""
    return len(lfs_download.download(repo, tracked(repo), "files of the team's Toolbox"))
