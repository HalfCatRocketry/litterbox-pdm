"""
people.py - who is on the team, what each person may do, and who the current user is.

THE FILE   .litterbox/people.yaml lives in the vault, so everybody gets the same copy through Git:

    roles: [Responsible Engineer, Manufacturing, Quality]     roles this org uses (Admins edit the list)
    people:
    - id: alex                      short, permanent, lowercase
      name: Alex Smith
      email: alex@example.com
      host_names: [alexsmith]       the names your Git host may report for this person (see "Who am I?")
      access: owner                 owner (exactly one) | admin | member
      roles: [Responsible Engineer]
      active: true
      signing_keys: ['ssh-ed25519 AAAA...']

ACCESS     Owner - exactly one; the only one who can hand over ownership; can do everything an Admin can.
           Admin - manages people, roles (and later workflows and overrides).
           Member - works on parts.
           Anyone who is not in the file, or whose entry is switched off, is READ-ONLY: they can look and
           open files, nothing else. A vault with no people file yet is in "legacy" mode: everybody may do
           everything (that is how a vault starts, until someone sets up the team).

WHO AM I   Litterbox never handles passwords: Git and the host sign you in. To learn which host account you are
           signed in as, it takes a lock on .litterbox/whoami, reads the owner name the host reports, and lets
           go again. That name is remembered in .git/litterbox-identity.json so Litterbox works offline, and is
           looked up again after a day (or when you press Who am I?). The person whose host_names include that
           name is you.

The checks here are process control: Git itself can't stop someone with push access from bypassing Litterbox.
The pre-push check, the audit on Get Latest and (optionally) the host's own CI are what catch that.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

import config
import litterbox_engine as eng

CONFIG_DIR = ".litterbox"
PEOPLE_FILE = f"{CONFIG_DIR}/people.yaml"
WHOAMI_FILE = f"{CONFIG_DIR}/whoami"
ALLOWED_SIGNERS_FILE = f"{CONFIG_DIR}/allowed_signers"
IDENTITY_CACHE = "litterbox-identity.json"
IDENTITY_MAX_AGE = 24 * 3600

OWNER, ADMIN, MEMBER = "owner", "admin", "member"
ACCESS_LEVELS = (OWNER, ADMIN, MEMBER)
ACCESS_LABEL = {OWNER: "Owner", ADMIN: "Admin", MEMBER: "Member"}

# What read-only people may still do
READ_ACTIONS = frozenset({"open", "open_drawing", "references", "history", "view"})
ADMIN_ACTIONS = frozenset({"manage_people"})
OWNER_ACTIONS = frozenset({"transfer_owner"})

STANDARD_ROLES = ["Responsible Engineer", "Manufacturing", "Quality", "Analysis", "Manager", "Chief"]

# States of the current user
LEGACY, OK, NOT_LISTED, INACTIVE, UNVERIFIED = "legacy", "ok", "not_listed", "inactive", "unverified"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


class PeopleError(eng.LitterboxError):
    """The people file is wrong, or a change to it is not allowed."""


# ---------------------------------------------------------------------------
# The data
# ---------------------------------------------------------------------------

@dataclass
class Person:
    id: str
    name: str
    email: str = ""
    host_names: list = field(default_factory=list)
    access: str = MEMBER
    roles: list = field(default_factory=list)
    active: bool = True
    signing_keys: list = field(default_factory=list)

    def to_dict(self):
        data = {"id": self.id, "name": self.name, "email": self.email, "host_names": list(self.host_names),
                "access": self.access, "roles": list(self.roles), "active": self.active}
        if self.signing_keys:
            data["signing_keys"] = list(self.signing_keys)
        return data

    @property
    def label(self):
        return ACCESS_LABEL.get(self.access, self.access)


@dataclass
class Directory:
    people: list = field(default_factory=list)
    roles: list = field(default_factory=list)

    def get(self, person_id):
        person_id = str(person_id).strip().lower()
        return next((p for p in self.people if p.id == person_id), None)

    def find_by_host_name(self, host_name):
        wanted = str(host_name or "").strip().lower()
        if not wanted:
            return None
        return next((p for p in self.people if wanted in (h.lower() for h in p.host_names)), None)

    def owner(self):
        return next((p for p in self.people if p.access == OWNER), None)

    def to_dict(self):
        return {"roles": list(self.roles), "people": [p.to_dict() for p in self.people]}


def _text_list(value, what):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        raise PeopleError(f"'{what}' must be a list.")
    return [str(v).strip() for v in value if str(v).strip()]


def from_dict(data):
    if not isinstance(data, dict):
        raise PeopleError(f"{PEOPLE_FILE} should contain 'roles' and 'people'.")
    people = []
    for entry in data.get("people") or []:
        if not isinstance(entry, dict):
            raise PeopleError("Every entry under 'people' must have an id, name and so on.")
        people.append(Person(
            id=str(entry.get("id", "")).strip().lower(), name=" ".join(str(entry.get("name", "")).split()),
            email=str(entry.get("email", "") or "").strip(),
            host_names=_text_list(entry.get("host_names"), "host_names"),
            access=str(entry.get("access", MEMBER)).strip().lower(),
            roles=_text_list(entry.get("roles"), "roles"),
            active=bool(entry.get("active", True)),
            signing_keys=_text_list(entry.get("signing_keys"), "signing_keys")))
    directory = Directory(people, _text_list(data.get("roles"), "roles"))
    validate(directory)
    return directory


def validate(directory):
    """Raise PeopleError if the directory breaks a rule. Also fixes the capitalisation of role names."""
    seen_ids, seen_hosts = set(), {}
    canon = {r.lower(): r for r in directory.roles}
    if len(canon) != len(directory.roles):
        raise PeopleError("The list of roles has the same role twice.")
    for role in directory.roles:
        if "," in role or "\n" in role:
            raise PeopleError(f"The role '{role}' can't contain a comma or a line break.")
    owners = 0
    for p in directory.people:
        if not _ID_RE.match(p.id):
            raise PeopleError(f"'{p.id}' is not a valid id. Use lowercase letters, numbers, '.', '-' or '_' "
                              "(for example 'alex').")
        if p.id in seen_ids:
            raise PeopleError(f"Two people have the id '{p.id}'.")
        seen_ids.add(p.id)
        if not p.name:
            raise PeopleError(f"{p.id} needs a name.")
        if p.email and "@" not in p.email:
            raise PeopleError(f"{p.name}: '{p.email}' doesn't look like an email address.")
        if p.access not in ACCESS_LEVELS:
            raise PeopleError(f"{p.name}: access must be owner, admin or member, not '{p.access}'.")
        owners += p.access == OWNER
        if p.access == OWNER and not p.active:
            raise PeopleError("The Owner can't be switched off. Hand over ownership first.")
        for host in p.host_names:
            key = host.lower()
            if key in seen_hosts and seen_hosts[key] != p.id:
                raise PeopleError(f"The host name '{host}' is listed for both {seen_hosts[key]} and {p.id}.")
            seen_hosts[key] = p.id
        roles = []
        for role in p.roles:
            if role.lower() not in canon:
                raise PeopleError(f"{p.name}: '{role}' is not one of this org's roles "
                                  f"({', '.join(directory.roles) or 'none defined yet'}).")
            roles.append(canon[role.lower()])
        p.roles = roles
        for key in p.signing_keys:
            if "\n" in key or not re.match(r"^(ssh-|ecdsa-|sk-)", key):
                raise PeopleError(f"{p.name}: a signing key must be one line starting with 'ssh-ed25519' or similar.")
    if directory.people and owners != 1:
        raise PeopleError(f"There must be exactly one Owner (found {owners}).")


def load(repo):
    """The vault's Directory, or None when the vault has no people file yet (legacy mode)."""
    path = Path(repo) / PEOPLE_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        raise PeopleError(f"Could not read {PEOPLE_FILE}: {e}")
    return from_dict(data)


def _dump(directory):
    return yaml.safe_dump(directory.to_dict(), sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=100)


def save(repo, directory):
    validate(directory)
    path = Path(repo) / PEOPLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, 0o644)
    tmp = path.with_name(".tmp-people.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(_dump(directory))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Who is the current user?
# ---------------------------------------------------------------------------

@dataclass
class Identity:
    state: str
    host_name: str = ""
    person: Person = None
    directory: Directory = None
    detail: str = ""

    @property
    def access(self):
        return self.person.access if self.state == OK and self.person else ""

    @property
    def name(self):
        return self.person.name if self.person else ""

    def allows(self, action):
        """(True, '') or (False, why not)."""
        if self.state == LEGACY or action in READ_ACTIONS:
            return True, ""
        if self.state != OK:
            return False, self.message()
        if action in OWNER_ACTIONS and self.access != OWNER:
            return False, "Only the Owner can do that."
        if action in ADMIN_ACTIONS and self.access not in (OWNER, ADMIN):
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
            roles = f", {', '.join(self.person.roles)}" if self.person.roles else ""
            return f"{self.person.name} ({self.person.label}{roles})"
        if self.state == NOT_LISTED:
            return "Not on the team list - read-only"
        if self.state == INACTIVE:
            return "Access switched off - read-only"
        return "Not verified - read-only"


def _cache_path(repo):
    return Path(repo) / ".git" / IDENTITY_CACHE


def _read_cache(repo):
    try:
        with open(_cache_path(repo), encoding="utf-8") as f:
            data = json.load(f)
        return str(data["host_name"]), float(data["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return "", 0.0


def _write_cache(repo, host_name):
    try:
        with open(_cache_path(repo), "w", encoding="utf-8") as f:
            json.dump({"host_name": host_name, "checked_at": time.time()}, f)
    except OSError:
        pass


def forget_identity(repo):
    try:
        _cache_path(repo).unlink()
    except OSError:
        pass


def probe_host_name(repo, attempts=5):
    """Ask the host who we are signed in as: lock .litterbox/whoami, read the owner, unlock. Needs the internet."""
    if not (Path(repo) / WHOAMI_FILE).is_file():
        raise PeopleError(f"{WHOAMI_FILE} is missing from the vault. Run Get Latest, or set up the team again.")
    last = None
    for attempt in range(attempts):
        try:
            eng.run(["git", "lfs", "lock", WHOAMI_FILE], repo, quiet=True)
            break
        except eng.LitterboxError as e:             # someone else is probing at this moment: wait and retry
            last = e
            time.sleep(0.5)
    else:
        raise PeopleError(f"Could not ask the host who you are. {last}")
    try:
        locks = eng.get_locks(repo, strict=True)
        mine = locks.get(WHOAMI_FILE.lower())
        if not mine or mine[0] != "you":
            raise PeopleError("The host did not say whose lock that was.")
        return mine[1]
    finally:
        try:
            eng.run(["git", "lfs", "unlock", "--force", WHOAMI_FILE], repo, quiet=True)
        except eng.LitterboxError:
            pass
        try:
            os.chmod(Path(repo) / WHOAMI_FILE, 0o644)
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
    directory = load(repo)
    if directory is None:
        return Identity(LEGACY)
    host_name, checked = _read_cache(repo)
    stale = (time.time() - checked) > IDENTITY_MAX_AGE
    error = ""
    if probe and (refresh or not host_name or stale):
        try:
            host_name = probe_host_name(repo)
            _write_cache(repo, host_name)
        except eng.LitterboxError as e:
            error = str(e).splitlines()[0] if str(e) else "offline?"
            if refresh:
                host_name = ""              # asked to check, and could not
    identity = resolve(directory, host_name)
    if identity.state == UNVERIFIED:
        identity.detail = error
    return identity


def require(repo, action):
    """Raise LitterboxError unless the current user may do `action`. Returns the Identity."""
    identity = current(repo)
    allowed, why = identity.allows(action)
    if not allowed:
        raise eng.LitterboxError(why)
    return identity


# ---------------------------------------------------------------------------
# Changes to the directory (pure: they change a Directory and say what they did)
# ---------------------------------------------------------------------------

def _rank(access):
    return {OWNER: 3, ADMIN: 2, MEMBER: 1}.get(access, 0)


def _may_change(actor, target):
    """Owners may change anyone but themselves-as-owner rules below; Admins may change Members only."""
    if actor.access == OWNER:
        return True
    return actor.access == ADMIN and target.access == MEMBER


def add_person(directory, actor, person_id, name, email="", host_names=(), access=MEMBER, roles=(),
               signing_keys=()):
    if access == OWNER:
        raise PeopleError("There is exactly one Owner. Use Transfer Ownership to change who it is.")
    if access == ADMIN and actor.access != OWNER:
        raise PeopleError("Only the Owner can make someone an Admin.")
    if directory.get(person_id):
        raise PeopleError(f"There is already someone with the id '{person_id}'.")
    person = Person(str(person_id).strip().lower(), " ".join(str(name).split()), str(email).strip(),
                    _text_list(list(host_names), "host_names"), access, _text_list(list(roles), "roles"), True,
                    _text_list(list(signing_keys), "signing_keys"))
    directory.people.append(person)
    validate(directory)
    return person


def update_person(directory, actor, person_id, **changes):
    """Change name, email, host_names, roles, signing_keys or access of one person."""
    person = directory.get(person_id)
    if person is None:
        raise PeopleError(f"There is nobody with the id '{person_id}'.")
    if person.id != actor.id and not _may_change(actor, person):
        raise PeopleError(f"You can't change {person.name}'s details.")
    allowed = {"name", "email", "host_names", "roles", "signing_keys", "access"}
    for key in changes:
        if key not in allowed:
            raise PeopleError(f"'{key}' can't be changed here.")
    if "access" in changes and changes["access"] != person.access:
        if person.access == OWNER or changes["access"] == OWNER:
            raise PeopleError("Use Transfer Ownership to change who the Owner is.")
        if actor.access != OWNER:
            raise PeopleError("Only the Owner can make someone an Admin or a Member.")
    if person.id == actor.id and actor.access != OWNER and ("roles" in changes):
        raise PeopleError("Ask an Admin to change your roles.")
    before = person.to_dict()
    for key, value in changes.items():
        if key in ("host_names", "roles", "signing_keys"):
            value = _text_list(value, key)
        elif key == "name":
            value = " ".join(str(value).split())
        setattr(person, key, value)
    try:
        validate(directory)
    except PeopleError:
        for key, value in before.items():
            setattr(person, key, value)
        raise
    return person


def set_active(directory, actor, person_id, active):
    person = directory.get(person_id)
    if person is None:
        raise PeopleError(f"There is nobody with the id '{person_id}'.")
    if person.access == OWNER:
        raise PeopleError("The Owner can't be switched off. Transfer ownership first.")
    if not _may_change(actor, person):
        raise PeopleError(f"You can't change {person.name}'s access. Only the Owner can switch an Admin off.")
    person.active = bool(active)
    return person


def transfer_owner(directory, actor, person_id):
    if actor.access != OWNER:
        raise PeopleError("Only the Owner can hand over ownership.")
    target = directory.get(person_id)
    if target is None:
        raise PeopleError(f"There is nobody with the id '{person_id}'.")
    if not target.active:
        raise PeopleError(f"{target.name} is switched off. Switch them on first.")
    if target.id == actor.id:
        raise PeopleError("You are already the Owner.")
    target.access, directory.get(actor.id).access = OWNER, ADMIN
    validate(directory)
    return target


def holders_of(directory, role):
    """Names of the people who have this role."""
    return [p.name for p in directory.people if role.lower() in (r.lower() for r in p.roles)]


def set_roles(directory, actor, roles, scrub=False):
    """Replace the list of roles this org uses.

    A role that somebody still holds can't be dropped, unless scrub=True, which takes it off everyone who
    has it (the Roles window asks the Admin to confirm that first)."""
    if actor.access not in (OWNER, ADMIN):
        raise PeopleError("Only an Admin can change the list of roles.")
    roles = [" ".join(r.split()) for r in _text_list(list(roles), "roles")]
    keep = {r.lower() for r in roles}
    for p in directory.people:
        gone = [r for r in p.roles if r.lower() not in keep]
        if gone and not scrub:
            raise PeopleError(f"{p.name} still has the role '{gone[0]}'. Take it off them first.")
        p.roles = [r for r in p.roles if r.lower() in keep]
    directory.roles = roles
    validate(directory)


# ---------------------------------------------------------------------------
# Saving changes to the vault (lock, pull, change, commit, push, unlock)
# ---------------------------------------------------------------------------

def allowed_signers_text(directory):
    """The file git uses to check signed commits: one line per signing key, named by the person's id."""
    lines = [f'{p.id} namespaces="git" {key}' for p in directory.people if p.active for key in p.signing_keys]
    return "\n".join(lines) + ("\n" if lines else "")


def _write_allowed_signers(repo, directory):
    text = allowed_signers_text(directory)
    path = Path(repo) / ALLOWED_SIGNERS_FILE
    if not text and not path.exists():
        return None
    if path.exists():
        os.chmod(path, 0o644)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return ALLOWED_SIGNERS_FILE


def _tracked(repo, rel):
    try:
        eng.run(["git", "ls-files", "--error-unmatch", "--", rel], repo, quiet=True)
        return True
    except eng.LitterboxError:
        return False


def edit_directory(repo, change, message, action="manage_people"):
    """Apply `change(directory, actor_person)` to the people file for everyone: lock it, get the latest,
    change it, commit, push, unlock. If anything fails the file is put back as it was.
    Returns whatever change() returns."""
    eng.validate_repo(repo)
    identity = require(repo, action)
    if identity.state == LEGACY:
        raise PeopleError("The team has not been set up yet. Use Set Up Team first.")
    rel = PEOPLE_FILE
    eng._lock(repo, rel, "the people file")
    committed, added_signers, result = False, False, None
    signers_before_tracked = _tracked(repo, ALLOWED_SIGNERS_FILE)
    try:
        eng._pull(repo)
        directory = load(repo)
        actor = directory.find_by_host_name(identity.host_name)
        if actor is None or not actor.active:
            raise PeopleError("Your access changed while you were working. Run Get Latest.")
        result = change(directory, actor)
        save(repo, directory)
        paths = [rel]
        signers = _write_allowed_signers(repo, directory)
        if signers:
            paths.append(signers)
            added_signers = not signers_before_tracked
        eng.run(["git", "add", "--"] + paths, repo)
        eng.run(["git", "commit", "-m", message, "--"] + paths, repo)
        committed = True
        eng._push_with_retry(repo)
    except BaseException:
        try:
            if committed:
                eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
            eng.run(["git", "restore", "--staged", "--worktree", "--", rel], repo)
            if signers_before_tracked:
                eng.run(["git", "restore", "--staged", "--worktree", "--", ALLOWED_SIGNERS_FILE], repo)
            elif added_signers or (Path(repo) / ALLOWED_SIGNERS_FILE).exists():
                eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", ALLOWED_SIGNERS_FILE], repo,
                        quiet=True)
                try:
                    (Path(repo) / ALLOWED_SIGNERS_FILE).unlink()
                except OSError:
                    pass
        except eng.LitterboxError as e:
            eng.LOG(f"WARNING: could not fully undo the change to {rel}: {e}")
        eng._force_unlock_quietly(repo, [rel])
        raise
    failed = eng._unlock_mine(repo, [rel])
    if failed:
        raise eng.LitterboxError(eng._unlock_failure_message(failed))
    return result


def setup_team(repo, name=None, email=None, roles=None):
    """Turn a vault with no people file into a managed one, with the person running this as its Owner.

    Needs the internet (the host has to tell Litterbox who you are). Two commits: the whoami file, then the
    people file. Returns the new Person."""
    eng.validate_repo(repo)
    if load(repo) is not None:
        raise PeopleError("This vault already has a team.")
    name = " ".join((name or eng.get_user(repo)).split())
    if not name:
        raise PeopleError("A name is required.")
    if email is None:
        try:
            email = eng.run(["git", "config", "user.email"], repo, quiet=True)
        except eng.LitterboxError:
            email = ""
    eng._pull(repo)
    whoami = Path(repo) / WHOAMI_FILE
    if not whoami.exists():
        whoami.parent.mkdir(parents=True, exist_ok=True)
        whoami.write_text("Litterbox takes a lock on this file to ask the host who you are. Leave it empty.\n",
                          encoding="utf-8")
        eng.run(["git", "add", "--", WHOAMI_FILE], repo)
        eng.run(["git", "commit", "-m", "Team: add whoami file", "--", WHOAMI_FILE], repo)
        eng._push_with_retry(repo)
    host_name = probe_host_name(repo)
    person_id = re.sub(r"[^a-z0-9._-]+", "-", host_name.lower()).strip("-.")[:40] or "owner"
    if not _ID_RE.match(person_id):
        person_id = "owner"
    directory = Directory([Person(person_id, name, email, [host_name], OWNER, [], True, [])],
                          list(roles if roles is not None else STANDARD_ROLES))
    save(repo, directory)
    try:
        eng.run(["git", "add", "--", PEOPLE_FILE], repo)
        eng.run(["git", "commit", "-m", f"Team: set up with {name} as Owner", "--", PEOPLE_FILE], repo)
        eng._push_with_retry(repo)
    except BaseException:
        try:
            eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
            eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", PEOPLE_FILE], repo, quiet=True)
            (Path(repo) / PEOPLE_FILE).unlink()
        except (eng.LitterboxError, OSError):
            pass
        raise
    _write_cache(repo, host_name)
    return directory.people[0]


# ---------------------------------------------------------------------------
# The check before anything is pushed
# ---------------------------------------------------------------------------

def check_before_push(repo):
    """Before a push: get the vault's latest people file and make sure it still lets this user push.

    This is how "you were switched off while you were away" is caught: the commits you made offline are
    not uploaded, and you are told why. A vault with no people file is not checked.
    """
    if load(repo) is None:
        return
    try:
        eng.run(["git", "fetch"], repo, quiet=True)
        text = eng.run(["git", "show", f"@{{u}}:{PEOPLE_FILE}"], repo, quiet=True)
    except eng.LitterboxError:
        return                                  # offline, or the vault has no people file yet: git will say if the push fails
    try:
        upstream = from_dict(yaml.safe_load(text) or {})
    except (yaml.YAMLError, PeopleError):
        return
    host_name, _checked = _read_cache(repo)
    identity = resolve(upstream, host_name)
    if identity.state in (NOT_LISTED, INACTIVE):
        raise PeopleError("Nothing was uploaded. " + identity.message().replace(
            "you can look but not change anything", "you can no longer upload changes")
            + "\nYour changes are still on your computer.")
    if config.get_require_signatures(repo):
        import signing
        bad = signing.untrusted_unpushed(repo)
        if bad:
            lines = "\n".join(f"  {s.subject} - {s.description}" for s in bad[:8])
            raise PeopleError("Nothing was uploaded. This vault requires every commit to be signed by a key on "
                              f"the team list, and these are not:\n{lines}\n\nUse Signing... to turn signing on "
                              "and give an Admin your public key. Your changes are still on your computer.")