"""
team_model.py - the team: people, their access level (Owner, Admin, Member) and roles, and checking a
team file is valid.

Exactly one Owner. Anyone not on the list, or switched off, is read-only. A vault with no people.yaml is in
"legacy" mode, where everyone may do everything.
"""

import re
from dataclasses import dataclass, field

from litterbox import layout
from litterbox.errors import LitterboxError


OWNER, ADMIN, MEMBER = "owner", "admin", "member"


ACCESS_LEVELS = (OWNER, ADMIN, MEMBER)


ACCESS_LABEL = {OWNER: "Owner", ADMIN: "Admin", MEMBER: "Member"}


# What read-only people may still do
READ_ACTIONS = frozenset({"open", "open_drawing", "references", "history", "view"})


ADMIN_ACTIONS = frozenset({"manage_people", "manage_workflows", "manage_settings", "override_release"})


OWNER_ACTIONS = frozenset({"transfer_owner"})


STANDARD_ROLES = ["Responsible Engineer", "Manufacturing", "Quality", "Analysis", "Manager", "Chief"]


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


class PeopleError(LitterboxError):
    """The people file is wrong, or a change to it is not allowed."""


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


def text_list(value, what):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        raise PeopleError(f"'{what}' must be a list.")
    return [str(v).strip() for v in value if str(v).strip()]


def from_dict(data):
    if not isinstance(data, dict):
        raise PeopleError(f"{layout.PEOPLE_FILE} should contain 'roles' and 'people'.")
    people = []
    for entry in data.get("people") or []:
        if not isinstance(entry, dict):
            raise PeopleError("Every entry under 'people' must have an id, name and so on.")
        people.append(Person(
            id=str(entry.get("id", "")).strip().lower(), name=" ".join(str(entry.get("name", "")).split()),
            email=str(entry.get("email", "") or "").strip(),
            host_names=text_list(entry.get("host_names"), "host_names"),
            access=str(entry.get("access", MEMBER)).strip().lower(),
            roles=text_list(entry.get("roles"), "roles"),
            active=bool(entry.get("active", True)),
            signing_keys=text_list(entry.get("signing_keys"), "signing_keys")))
    directory = Directory(people, text_list(data.get("roles"), "roles"))
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
        if not ID_PATTERN.match(p.id):
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
