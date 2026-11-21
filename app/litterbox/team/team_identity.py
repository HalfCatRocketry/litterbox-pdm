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
from litterbox.team import team_model
from litterbox.team import team_store


IDENTITY_CACHE = "litterbox-identity.json"

IDENTITY_MAX_AGE = 24 * 3600

# After the host could not be asked (offline, not signed in, no Write access), an ordinary refresh waits this long
# before asking again, so a sign-in that keeps failing doesn't open a sign-in window at every refresh. Who am I?
# (refresh=True) always asks.
PROBE_RETRY_AFTER = 10 * 60

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
        if self.state == UNVERIFIED and self.detail.endswith("."):      # a reason that says what to do
            return ("Litterbox could not find out which account you are signed in as. " + self.detail
                    + " You can still look at parts and open files.")
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


def _read_cache_data(repo):
    try:
        with open(cache_path(repo), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache_data(repo, data):
    try:
        with open(cache_path(repo), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def write_cache(repo, host_name):
    """Remember the host's answer (and forget any failure noted before it)."""
    _write_cache_data(repo, {"host_name": host_name, "checked_at": time.time()})


def note_probe_failure(repo, detail):
    """Remember that the host could not be asked just now, and why. A name remembered before is kept."""
    data = _read_cache_data(repo)
    data.update(failed_at=time.time(), failure=detail)
    _write_cache_data(repo, data)


def recent_probe_failure(repo):
    """Why the host could not be asked, if that was less than PROBE_RETRY_AFTER ago; otherwise None."""
    data = _read_cache_data(repo)
    try:
        failed_at = float(data.get("failed_at", 0))
    except (TypeError, ValueError):
        return None
    if not failed_at or not 0 <= time.time() - failed_at <= PROBE_RETRY_AFTER:
        return None
    return str(data.get("failure") or "")


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
    for _attempt in range(attempts):
        try:
            lfs_locks.run_lfs(["git", "lfs", "lock", layout.WHOAMI_FILE], repo, quiet=True)
            break
        except LitterboxError as e:
            if not lock_is_busy(e):             # not signed in, no Write access, offline: asking again won't help,
                raise team_model.PeopleError(probe_failure_text(e)) from None    # and may open another sign-in
            last = e                            # someone else is probing at this moment: wait and retry
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
            lfs_locks.run_lfs(["git", "lfs", "unlock", "--force", layout.WHOAMI_FILE], repo, quiet=True)
        except LitterboxError:
            pass
        try:
            os.chmod(Path(repo) / layout.WHOAMI_FILE, 0o644)
        except OSError:
            pass


HOST_NOT_REACHED = ("Git couldn't reach the vault's host: you may be offline, or not signed in with the account that "
                    "was invited to the vault's repository. Press Who am I? to try again.")

_BUSY = ("lock exists", "already locked", "already created")
_NO_WRITE = ("403", "forbidden", "push access", "write access", "permission", "not authorized")
_NOT_SIGNED_IN = ("401", "authentication failed", "invalid credentials", "could not read username",
                  "terminal prompts disabled", "unauthorized")
_NOT_FOUND = ("404", "repository not found", "not found")


def lock_is_busy(error):
    """True if taking the whoami lock failed only because someone else holds it at this moment."""
    text = str(error).lower()
    return any(word in text for word in _BUSY)


def probe_failure_text(error):
    """Why the host couldn't say who you are, in words a person can act on."""
    text = str(error).lower()
    if any(word in text for word in _NO_WRITE):
        return ("The host won't let this account lock files in the vault, which Litterbox needs to learn who you "
                "are. Ask the repository's owner to give your account the Write role (on GitHub: the repository's "
                "Settings > Collaborators and teams), and accept the invitation if one was sent.")
    if any(word in text for word in _NOT_SIGNED_IN):
        return ("Git isn't signed in to the host. When the sign-in window opens, sign in with the account that was "
                "invited to the vault's repository, then press Who am I?.")
    if any(word in text for word in _NOT_FOUND):
        return ("The host can't find the vault's repository for this account. Check that you accepted the "
                "invitation and signed in with the account that was invited.")
    lines = [line for line in str(error).strip().splitlines() if line.strip()]
    return "Could not ask the host who you are" + (f" ({lines[-1].strip()})" if lines else " (offline?)") + "."


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
    used, even an old one; with none at all the user is UNVERIFIED. After a failed attempt the host isn't asked
    again for PROBE_RETRY_AFTER unless refresh=True, so a sign-in that keeps failing can't open a sign-in window
    at every refresh.
    """
    directory = team_store.load(repo)
    if directory is None:
        return Identity(LEGACY)
    host_name, checked = read_cache(repo)
    stale = (time.time() - checked) > IDENTITY_MAX_AGE
    error = ""
    if probe and (refresh or not host_name or stale):
        failed = None if refresh else recent_probe_failure(repo)
        if failed is not None:
            error = failed                  # failed a few minutes ago: wait, or press Who am I?
        else:
            try:
                host_name = probe_host_name(repo)
                write_cache(repo, host_name)
            except LitterboxError as e:
                error = str(e).splitlines()[0] if str(e) else "offline?"
                note_probe_failure(repo, error)
                if refresh:
                    host_name = ""          # asked to check, and could not
    identity = resolve(directory, host_name)
    if identity.state == UNVERIFIED:
        identity.detail = error
    return identity
