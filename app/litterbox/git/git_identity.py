"""
git_identity.py - the name and email address git puts on your commits (user.name, user.email). Without both, git
refuses to commit, so nothing could be uploaded. Litterbox asks for them and sets them for one vault only
(git config --local), never for the whole computer.

    git_identity.current(repo)                    # ("Alex Smith", "alex@x.com"), "" for one not set
    git_identity.wanted(current, team_name, team_email)
    git_identity.save(repo, "Alex Smith", "alex@x.com")
"""

from dataclasses import dataclass

from litterbox.errors import LitterboxError
from litterbox.git import runner

NAME_MAX = 100


@dataclass(frozen=True)
class Wanted:
    """What to ask: `missing` (name and/or email not set) or `differs` (git's name isn't the team list's), with
    the values to start the form with."""
    missing: tuple = ()             # "name", "email"
    differs: bool = False
    name: str = ""
    email: str = ""

    @property
    def needed(self):
        return bool(self.missing or self.differs)


def _get(repo, key):
    try:
        return runner.run(["git", "config", key], repo, quiet=True).strip()
    except LitterboxError:                  # not set: git config exits 1
        return ""


def current(repo):
    """(name, email) git uses in this folder (set for the vault, or for the whole computer); "" for one not set."""
    return _get(repo, "user.name"), _get(repo, "user.email")


def wanted(now, team_name="", team_email=""):
    """What to ask for, given current() and your name and email on the team list ("" if not known): any missing
    one (the form starts with the team list's), or the team list's name when git has another."""
    name, email = now
    missing = tuple(what for what, value in (("name", name), ("email", email)) if not value)
    differs = bool(not missing and team_name and name != team_name)
    start = team_name if differs or not name else name
    return Wanted(missing, differs, start, email or team_email)


def check(name, email):
    """(name, email) tidied; raises LitterboxError, safe to show, if either won't do."""
    name, email = " ".join(str(name or "").split()), str(email or "").strip()
    if not name:
        raise LitterboxError("Enter your name.")
    if len(name) > NAME_MAX:
        raise LitterboxError(f"That name is too long (at most {NAME_MAX} characters).")
    if not email or " " in email or email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        raise LitterboxError("Enter your email address (like name@example.com).")
    return name, email


def save(repo, name, email):
    """Set the name and email git uses in this vault only. Returns them, tidied. Raises LitterboxError."""
    name, email = check(name, email)
    runner.run(["git", "config", "--local", "user.name", name], repo)
    runner.run(["git", "config", "--local", "user.email", email], repo)
    return name, email
