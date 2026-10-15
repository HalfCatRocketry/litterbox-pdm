"""
team_identity.py - who you are on this vault's team.

Litterbox never handles passwords: Git and the host sign people in. Taking the LFS lock on .litterbox/whoami shows
which host account is in use, and that is matched to a person in the team file. The answer is cached for a day.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import runner
from litterbox.team import team_model
from litterbox.team import team_store


IDENTITY_CACHE = "litterbox-identity.json"


IDENTITY_MAX_AGE = 24 * 3600


# States of the current user
LEGACY, OK, NOT_LISTED, INACTIVE, UNVERIFIED = "legacy", "ok", "not_listed", "inactive", "unverified"


@dataclass
class Identity:
    state: str
    host_name: str = ""
    person: team_model.Person = None
    directory: team_model.Directory = None
    detail: str = ""

    @property
    def access(self):
        return self.person.access if self.state == OK and self.person else ""

    @property
    def name(self):
        return self.person.name if self.person else ""

    def allows(self, action):
        """(True, '') or (False, why not)."""
        if self.state == LEGACY or action in team_model.READ_ACTIONS:
            return True, ""
        if self.state != OK:
            return False, self.message()
        if action in team_model.OWNER_ACTIONS and self.access != team_model.OWNER:
            return False, "Only the Owner can do that."
        if action in team_model.ADMIN_ACTIONS and self.access not in (team_model.OWNER, team_model.ADMIN):
            return False, "Only an Admin can do that."
        return True, ""

    def message(self):
        if self.state == NOT_LISTED:
            shown = f" (the host knows you as '{self.host_name}')" if self.host_name else ""
            return f"You are not on this vault's team list{shown}, so you can look but not change anything. Ask an Admin to add you."
        if self.state == INACTIVE:
            return "Your access to this vault has been switched off. Ask an Admin."
        if self.state == UNVERIFIED:
            return ("Litterbox could not find out which account you are signed in as"
                    + (f" ({self.detail})" if self.detail else "") + ". Connect to the internet and press Who am I?, "
                    "then try again. You can still look at parts and open files.")
        return ""

    def describe(self):
        """One line for the window."""
        if self.state == LEGACY:
            return "Team not set up - everyone can do everything"
        if self.state == OK:
            return self.person.name
        if self.state == NOT_LISTED:
            return "Not on the team list - read-only"
        if self.state == INACTIVE:
            return "Access switched off - read-only"
        return "Not verified - read-only"


def cache_path(repo):
    return Path(repo) / ".git" / IDENTITY_CACHE


def read_cache(repo):
    try:
        with open(cache_path(repo), encoding="utf-8") as f:
            data = json.load(f)
        return str(data["host_name"]), float(data["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return "", 0.0


def write_cache(repo, host_name):
    try:
        with open(cache_path(repo), "w", encoding="utf-8") as f:
            json.dump({"host_name": host_name, "checked_at": time.time()}, f)
    except OSError:
        pass


def forget_identity(repo):
    try:
        cache_path(repo).unlink()
    except OSError:
        pass


def probe_host_name(repo, attempts=5):
    """Ask the host who we are signed in as: lock .litterbox/whoami, read the owner, unlock. Needs the internet."""
    if not (Path(repo) / layout.WHOAMI_FILE).is_file():
        raise team_model.PeopleError(f"{layout.WHOAMI_FILE} is missing from the vault. Run Get Latest, or set up the team again.")
    last = None
    for attempt in range(attempts):
        try:
            runner.run(["git", "lfs", "lock", layout.WHOAMI_FILE], repo, quiet=True)
            break
        except LitterboxError as e:             # someone else is probing at this moment: wait and retry
            last = e
            time.sleep(0.5)
    else:
        raise team_model.PeopleError(f"Could not ask the host who you are. {last}")
    try:
        locks = lfs_locks.get_locks(repo, strict=True)
        mine = locks.get(layout.WHOAMI_FILE.lower())
        if not mine or mine[0] != "you":
            raise team_model.PeopleError("The host did not say whose lock that was.")
        return mine[1]
    finally:
        try:
            runner.run(["git", "lfs", "unlock", "--force", layout.WHOAMI_FILE], repo, quiet=True)
        except LitterboxError:
            pass
        try:
            os.chmod(Path(repo) / layout.WHOAMI_FILE, 0o644)
        except OSError:
            pass


def resolve(directory, host_name):
    if directory is None:
        return Identity(LEGACY)
    if not host_name:
        return Identity(UNVERIFIED, directory=directory)
    person = directory.find_by_host_name(host_name)
    if person is None:
        return Identity(NOT_LISTED, host_name, None, directory)
    if not person.active:
        return Identity(INACTIVE, host_name, person, directory)
    return Identity(OK, host_name, person, directory)


def current(repo, refresh=False, probe=True):
    """Who the current user is, as an Identity.

    The host account name is remembered for a day. refresh=True asks the host again. probe=False never
    uses the internet (it uses what is remembered). If the host can't be reached, a remembered name is
    used, even an old one; with none at all the user is UNVERIFIED.
    """
    directory = team_store.load(repo)
    if directory is None:
        return Identity(LEGACY)
    host_name, checked = read_cache(repo)
    stale = (time.time() - checked) > IDENTITY_MAX_AGE
    error = ""
    if probe and (refresh or not host_name or stale):
        try:
            host_name = probe_host_name(repo)
            write_cache(repo, host_name)
        except LitterboxError as e:
            error = str(e).splitlines()[0] if str(e) else "offline?"
            if refresh:
                host_name = ""              # asked to check, and could not
    identity = resolve(directory, host_name)
    if identity.state == UNVERIFIED:
        identity.detail = error
    return identity
