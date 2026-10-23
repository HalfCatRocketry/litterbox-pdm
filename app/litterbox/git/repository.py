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
    """Return the set of lowercase paths with uncommitted changes (including brand-new files; a renamed file under
    both its names).

    git's machine-readable status (version 2, entries ended by NUL) is used, so a name with spaces or letters like
    é comes back exactly as it is, never quoted or escaped."""
    out = runner.run(["git", "status", "--porcelain=v2", "-z", "--untracked-files=all"], repo, quiet=True)
    modified, entries = set(), iter(out.split("\0"))
    for entry in entries:
        kind = entry[:1]
        if kind == "1":                         # changed: 1 XY sub mH mI mW hH hI path
            modified.add(entry.split(" ", 8)[-1].lower())
        elif kind == "2":                       # renamed or copied: 2 XY sub mH mI mW hH hI Xscore path, then the old path
            modified.add(entry.split(" ", 9)[-1].lower())
            modified.add(next(entries, "").lower())
        elif kind == "u":                       # unmerged: u XY sub m1 m2 m3 mW h1 h2 h3 path
            modified.add(entry.split(" ", 10)[-1].lower())
        elif kind == "?":                       # untracked: ? path
            modified.add(entry[2:].lower())
    modified.discard("")
    return modified


def head(repo):
    return runner.run(["git", "rev-parse", "HEAD"], repo, quiet=True)


def changed_between(repo, before, after):
    """Paths that differ between two commits."""
    if before == after:
        return []
    out = runner.run(["git", "diff", "--name-only", before, after], repo, quiet=True)
    return [line for line in out.splitlines() if line]


UNPUSHED = "@{u}..HEAD"          # your commits that are not uploaded yet
INCOMING = "HEAD..@{u}"          # the vault's commits you haven't got yet (as of the last fetch)


def paths_changed_in(repo, rev_range):
    """Every path that the commits in rev_range (UNPUSHED, INCOMING) change, in one look at git, so a batch of parts
    asks once ("does any of these commits touch this part's files?" is then a set lookup). An empty set when there
    are none, or when git can't tell (no upstream branch, say)."""
    try:
        out = runner.run(["git", "log", "--format=", "--name-only", "--no-renames", "-z", rev_range], repo, quiet=True)
    except LitterboxError:
        return set()
    return set(out.replace("\n", "\0").split("\0")) - {""}


def quiet_output(repo, *args):
    """The output of `git <args>`, without logging the command; '' if it fails."""
    try:
        return runner.run(["git", *args], repo, quiet=True)
    except LitterboxError:
        return ""


def in_head(repo, rel):
    """True if the latest commit has this file (so it belongs to the vault, not to a half-finished import)."""
    return bool(quiet_output(repo, "ls-tree", "HEAD", "--", rel))


def in_head_many(repo, rels):
    """The ones of these files the latest commit has (in_head for many), asking git once for every 100."""
    rels = list(rels)
    if not rels:
        return set()
    try:
        out = runner.run_chunked(["git", "ls-tree", "--name-only", "-z", "HEAD"], rels, repo, quiet=True)
    except LitterboxError:
        return set()
    found = set(out.replace("\n", "\0").split("\0"))
    return {rel for rel in rels if rel in found}


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
