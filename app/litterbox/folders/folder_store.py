"""
folder_store.py - the Team and project folders, kept in the vault's folders/ folder as changes nobody ever edits:
one small file per change, so two people changing folders at once never clash in git (no locks), and the history
comes free. Every file read in order (by name: the time, then a random part) builds the trees
(folders/folder_model.py).

    folders/20261024T101500123456Z-3f2a9c1b.yaml
        at: '2026-10-24T10:15:00Z'
        by: Alex Smith
        scope: team                 # or project, with
        project: Rover              #   the project's name
        ops:
        - {op: add, folder: 5d0e77aa, parent: '', name: Brackets}

When a project is renamed, a change with {op: project_renamed, name: <new name>} carries its folders over.

    trees = folder_store.load(repo)                    # Trees: .team, .projects {name: tree}
    folder_store.save_change(repo, TEAM, None, ops, "Brackets: added")      # write, commit, upload

An older Litterbox doesn't know this folder and leaves it alone, so nothing here raises the vault's minimum version.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.folders import folder_access
from litterbox.folders import folder_model
from litterbox.git import committing
from litterbox.git import repository
from litterbox.git import runner
from litterbox.util import fast_yaml

RENAMED = "project_renamed"


@dataclass
class Trees:
    team: dict = field(default_factory=dict)
    projects: dict = field(default_factory=dict)        # project name -> tree


def folder(repo):
    return Path(repo) / layout.FOLDERS_DIR_NAME


def change_files(repo):
    """Every change file, in the order they apply."""
    where = folder(repo)
    return sorted(where.glob("*.yaml")) if where.is_dir() else []


def read_change(path):
    """(scope, project name, [ops]) from one change file; None for one that can't be read (it is skipped)."""
    try:
        data = fast_yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        diagnostics.LOG(f"WARNING: skipped a folder change that can't be read ({Path(path).name}): {e}")
        return None
    if not isinstance(data, dict) or data.get("scope") not in (folder_access.TEAM, folder_access.PROJECT):
        return None
    ops = [op for op in data.get("ops") or [] if isinstance(op, dict)]
    return data["scope"], str(data.get("project") or ""), ops


def load(repo):
    """The Team tree and every project's tree, from every change in the vault."""
    trees = Trees()
    for path in change_files(repo):
        read = read_change(path)
        if read is None:
            continue
        scope, project, ops = read
        if scope == folder_access.TEAM:
            tree = trees.team
        else:
            key = next((name for name in trees.projects if name.lower() == project.lower()), project)
            tree = trees.projects.setdefault(key, {})
        for op in ops:
            if op.get("op") == RENAMED and scope == folder_access.PROJECT:
                new = str(op.get("name") or "")
                if new:
                    trees.projects[new] = trees.projects.pop(key, {})
            else:
                folder_model.apply(tree, op)
    return trees


def tree_of(trees, scope, project=None):
    """The tree of a scope (a project's by name; {} if it has none yet)."""
    if scope == folder_access.TEAM:
        return trees.team
    return next((tree for name, tree in trees.projects.items() if name.lower() == str(project or "").lower()), {})


def _now():
    return datetime.now(timezone.utc)


STAMP = "%Y%m%dT%H%M%S%fZ"


def _next_time(repo):
    """Now, or just after the newest change here if that is later: Windows' clock can give two quick changes the
    same time, and changes apply in the order of their names."""
    when = _now()
    files = change_files(repo)
    if files:
        try:
            newest = datetime.strptime(files[-1].name.split("-", 1)[0], STAMP).replace(tzinfo=timezone.utc)
        except ValueError:
            return when
        if newest >= when:
            return newest + timedelta(microseconds=1)
    return when


def write_change(repo, scope, project, ops, by):
    """Write one change file and return its path relative to the vault."""
    when = _next_time(repo)
    name = f"{when.strftime(STAMP)}-{secrets.token_hex(4)}.yaml"
    data = {"at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "by": by, "scope": scope}
    if scope == folder_access.PROJECT:
        data["project"] = project
    data["ops"] = [dict(op) for op in ops]
    target = folder(repo) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "x", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    return f"{layout.FOLDERS_DIR_NAME}/{name}"


def save_change(repo, scope, project, ops, message, push=None):
    """Write, commit and upload one change (Team or a project's). `push(repo)` uploads (team/guarded_push.push in
    the program). If the upload fails the commit stays here, and goes up with the next upload."""
    if not ops:
        return None
    repository.validate_repo(repo)
    rel = write_change(repo, scope, project, ops, repository.get_user(repo))
    try:
        runner.run(["git", "add", "--", rel], repo)
        committing.commit_paths(repo, f"Folders: {message}", "", [rel])
    except LitterboxError:
        try:
            runner.run(["git", "reset", "-q", "--", rel], repo)
        except LitterboxError:
            pass
        (Path(repo) / rel).unlink(missing_ok=True)
        raise
    if push is not None:
        try:
            push(repo)
        except folder_access.FoldersRefused:
            _take_back(repo, rel, f"Folders: {message}")
            raise
    return rel


def _take_back(repo, rel, subject):
    """A refused change: our commit (if it is the newest one, still not uploaded) and its file go, so they don't
    stop every later upload."""
    try:
        if runner.run(["git", "log", "-1", "--format=%s"], repo, quiet=True) == subject and                 runner.run(["git", "rev-list", "--count", repository.UNPUSHED], repo, quiet=True) != "0":
            runner.run(["git", "reset", "-q", "--soft", "HEAD~1"], repo)
        runner.run(["git", "reset", "-q", "--", rel], repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: a refused folder change couldn't be fully taken back ({rel}): {e}")
    (Path(repo) / rel).unlink(missing_ok=True)


def unpushed_changes(repo, paths):
    """[(scope, project)] of the change files among `paths` (relative to the vault): the folder changes an upload
    carries."""
    prefix = layout.FOLDERS_DIR_NAME.lower() + "/"
    found = []
    for rel in paths:
        if rel.lower().startswith(prefix) and rel.lower().endswith(".yaml"):
            read = read_change(Path(repo) / rel)
            if read is not None and any(op.get("op") != RENAMED for op in read[2]):
                found.append(read[:2])                  # (a project's rename was checked when it was edited)
    return found
