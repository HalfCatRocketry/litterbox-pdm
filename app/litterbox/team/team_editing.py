"""
team_editing.py - changes to the team, in memory: adding and changing people, switching them on and off,
handing over the Owner role, and the list of roles. Saving is team_store.edit_directory.
"""

from litterbox.team import team_model
from litterbox.team import team_permissions


def add_person(directory, actor, person_id, name, email="", host_names=(), access=team_model.MEMBER, roles=(),
               signing_keys=()):
    if access == team_model.OWNER:
        raise team_model.PeopleError("There is exactly one Owner. Use Transfer Ownership to change who it is.")
    if access == team_model.ADMIN and actor.access != team_model.OWNER:
        raise team_model.PeopleError("Only the Owner can make someone an Admin.")
    if directory.get(person_id):
        raise team_model.PeopleError(f"There is already someone with the id '{person_id}'.")
    person = team_model.Person(str(person_id).strip().lower(), " ".join(str(name).split()), str(email).strip(),
                    team_model._text_list(list(host_names), "host_names"), access, team_model._text_list(list(roles), "roles"), True,
                    team_model._text_list(list(signing_keys), "signing_keys"))
    directory.people.append(person)
    team_model.validate(directory)
    return person


def update_person(directory, actor, person_id, **changes):
    """Change name, email, host_names, roles, signing_keys or access of one person."""
    person = directory.get(person_id)
    if person is None:
        raise team_model.PeopleError(f"There is nobody with the id '{person_id}'.")
    if person.id != actor.id and not team_permissions.may_change(actor, person):
        raise team_model.PeopleError(f"You can't change {person.name}'s details.")
    allowed = {"name", "email", "host_names", "roles", "signing_keys", "access"}
    for key in changes:
        if key not in allowed:
            raise team_model.PeopleError(f"'{key}' can't be changed here.")
    if "access" in changes and changes["access"] != person.access:
        if person.access == team_model.OWNER or changes["access"] == team_model.OWNER:
            raise team_model.PeopleError("Use Transfer Ownership to change who the Owner is.")
        if actor.access != team_model.OWNER:
            raise team_model.PeopleError("Only the Owner can make someone an Admin or a Member.")
    if person.id == actor.id and actor.access != team_model.OWNER and ("roles" in changes):
        raise team_model.PeopleError("Ask an Admin to change your roles.")
    before = person.to_dict()
    for key, value in changes.items():
        if key in ("host_names", "roles", "signing_keys"):
            value = team_model._text_list(value, key)
        elif key == "name":
            value = " ".join(str(value).split())
        setattr(person, key, value)
    try:
        team_model.validate(directory)
    except team_model.PeopleError:
        for key, value in before.items():
            setattr(person, key, value)
        raise
    return person


def set_active(directory, actor, person_id, active):
    person = directory.get(person_id)
    if person is None:
        raise team_model.PeopleError(f"There is nobody with the id '{person_id}'.")
    if person.access == team_model.OWNER:
        raise team_model.PeopleError("The Owner can't be switched off. Transfer ownership first.")
    if not team_permissions.may_change(actor, person):
        raise team_model.PeopleError(f"You can't change {person.name}'s access. Only the Owner can switch an Admin off.")
    person.active = bool(active)
    return person


def transfer_owner(directory, actor, person_id):
    if actor.access != team_model.OWNER:
        raise team_model.PeopleError("Only the Owner can hand over ownership.")
    target = directory.get(person_id)
    if target is None:
        raise team_model.PeopleError(f"There is nobody with the id '{person_id}'.")
    if not target.active:
        raise team_model.PeopleError(f"{target.name} is switched off. Switch them on first.")
    if target.id == actor.id:
        raise team_model.PeopleError("You are already the Owner.")
    target.access, directory.get(actor.id).access = team_model.OWNER, team_model.ADMIN
    team_model.validate(directory)
    return target


def holders_of(directory, role):
    """Names of the people who have this role."""
    return [p.name for p in directory.people if role.lower() in (r.lower() for r in p.roles)]


def set_roles(directory, actor, roles, scrub=False):
    """Replace the list of roles this org uses.

    A role that somebody still holds can't be dropped, unless scrub=True, which takes it off everyone who
    has it (the Roles window asks the Admin to confirm that first)."""
    if actor.access not in (team_model.OWNER, team_model.ADMIN):
        raise team_model.PeopleError("Only an Admin can change the list of roles.")
    roles = [" ".join(r.split()) for r in team_model._text_list(list(roles), "roles")]
    keep = {r.lower() for r in roles}
    for p in directory.people:
        gone = [r for r in p.roles if r.lower() not in keep]
        if gone and not scrub:
            raise team_model.PeopleError(f"{p.name} still has the role '{gone[0]}'. Take it off them first.")
        p.roles = [r for r in p.roles if r.lower() in keep]
    directory.roles = roles
    team_model.validate(directory)
