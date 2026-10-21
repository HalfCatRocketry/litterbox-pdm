"""
repository.py - facts about the vault's git repository: is it a vault, who
is the user, which files are modified, and what changed between two commits.
"""

from pathlib import Path

from litterbox.errors import LitterboxError
from litterbox.git import runner
from litterbox.util import person_name
from litterbox.vault import config


def validate_repo(repo):
    repo = Path(repo)
    if not repo.is_dir():
        raise LitterboxError(f"Repo folder not found:\n{repo}")
    if not (repo / ".git").exists():
        raise LitterboxError(f"This folder is not a git repo (no .git folder):\n{repo}")
    try:
        config.apply(repo)          # learn how this vault writes its part numbers (digit counts)
    except config.ConfigError as e:
        raise LitterboxError(str(e)) from e


def get_user(repo):
    """Your name, for the history. In a vault with a team list it is your name on that list (as last
    verified with the host), carrying your id on it (a person_name.PersonName); otherwise it is the name git has
    for you."""
    try:
        from litterbox.team import team_identity
        identity = team_identity.current(repo, probe=False)
        if identity.state == team_identity.OK:
            return person_name.PersonName(identity.name, identity.person.id)
    except LitterboxError:
        pass
    try:
        name = runner.run(["git", "config", "user.name"], repo, quiet=True)
    except LitterboxError:
        name = ""
    if not name:
        raise LitterboxError(
            "Git doesn't know your name yet. Run this once, then try again:\n"
            '  git config --global user.name "Your Name"'
        )
    return name


def get_modified(repo):
    """Return the set of lowercase paths with uncommitted changes (including brand-new files)."""
    out = runner.run(["git", "status", "--porcelain", "--untracked-files=all"], repo, quiet=True)
    modified = set()
    for line in out.splitlines():
        _flag, _, path = line.strip().partition(" ")
        modified.add(path.strip().strip('"').lower())
    return modified


def head(repo):
    return runner.run(["git", "rev-parse", "HEAD"], repo, quiet=True)


def changed_between(repo, before, after):
    """Paths that differ between two commits."""
    if before == after:
        return []
    out = runner.run(["git", "diff", "--name-only", before, after], repo, quiet=True)
    return [line for line in out.splitlines() if line]


def count(repo, rev_range, paths):
    """How many commits in rev_range touch these paths? None if git can't tell
    (for example, no upstream branch is set)."""
    try:
        return int(runner.run(["git", "rev-list", "--count", rev_range, "--"] + list(paths), repo, quiet=True))
    except (LitterboxError, ValueError):
        return None


def quiet_output(repo, *args):
    """The output of `git <args>`, without logging the command; '' if it fails."""
    try:
        return runner.run(["git", *args], repo, quiet=True)
    except LitterboxError:
        return ""


def in_head(repo, rel):
    """True if the latest commit has this file (so it belongs to the vault, not to a half-finished import)."""
    return bool(quiet_output(repo, "ls-tree", "HEAD", "--", rel))


def tracked(repo, pattern):
    """The files git tracks that match a path pattern (like 'documents/PROP-0001_A.*'), as git spells them."""
    try:
        return runner.run(["git", "ls-files", "--", pattern], repo, quiet=True).splitlines()
    except LitterboxError:
        return []


def in_index(repo, rel):
    """True if git tracks this file (it is in the index: committed, or added)."""
    try:
        runner.run(["git", "ls-files", "--error-unmatch", "--", rel], repo, quiet=True)
        return True
    except LitterboxError:
        return False
