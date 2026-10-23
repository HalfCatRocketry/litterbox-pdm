"""
project_access.py - who may do what in a restricted or hidden project (core/projects.py).

    may_work    make its part numbers, change its parts, ask for and withdraw their workflows: its members and Lead,
                and Admins and the Owner (an override). Anyone, in a project that isn't restricted.
    may_see     see it and its parts at all: the same people, in a hidden project. Anyone, otherwise.
    may_edit    change the project's Lead, members, Restrict, Hide and name: Admins, the Owner and its Lead.
    may_sign    be named on, or sign, a sign-off of its parts: the people who may work on it, and superusers when it
                isn't hidden.

A vault without a team file lets everybody do everything, as everywhere else. These checks are process control, not
security: someone with push access can bypass Litterbox.

    project_access.require_work(repo, ["Rover"], "check out HCR-120001-001")
"""

from dataclasses import replace

from litterbox.errors import LitterboxError
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.vault import config


def overrides(person):
    """Admins and the Owner may do anything in any project."""
    return bool(person and person.active and person.access in (team_model.OWNER, team_model.ADMIN))


def may_work(person, project, legacy=False):
    if project is None or not project.restricted or legacy:
        return True
    return overrides(person) or bool(person and person.active and project.is_member(person.id))


def may_see(person, project, legacy=False):
    if project is None or not project.hidden:
        return True
    return may_work(person, project, legacy)


def may_edit(person, project, legacy=False):
    if legacy or overrides(person):
        return True
    return bool(project and person and person.active and person.id == project.lead)


def may_sign(directory, person, project):
    """`directory` is the team (team_model.Directory), for who is a superuser."""
    if directory is None or may_work(person, project):
        return True
    return not project.hidden and directory.is_superuser(person)


def signers(directory, people, projects):
    """The people among `people` who may sign for parts in all of these projects."""
    return [p for p in people if all(may_sign(directory, p, project) for project in projects)]


def usable(person, projects, legacy=False):
    """The projects New Part, New Assembly and Import offer this person: those they may work on."""
    return [p for p in projects if may_work(person, p, legacy)]


def visible(person, projects, legacy=False):
    """The projects this person may see."""
    return [p for p in projects if may_see(person, p, legacy)]


def lead_name(directory, project):
    lead = directory.get(project.lead) if directory is not None and project.lead else None
    return lead.name if lead else project.lead


def refusal(directory, project, what):
    """Why someone outside a restricted project can't `what` ('check out HCR-120001-001')."""
    lead = lead_name(directory, project)
    ask = f" Ask {lead}, its Lead, to add you." if lead else ""
    return f"You can't {what}: project {project.name} is restricted to its members.{ask}"


# -- for the actions -----------------------------------------------------------
def current(repo):
    """(the Identity, legacy) of the current user, without asking the host again (the action's own permission
    check just did)."""
    identity = team_identity.current(repo, probe=False)
    return identity, identity.state == team_identity.LEGACY


def projects_named(repo, names):
    """The projects with these names (none for '' or a name no longer in the settings)."""
    wanted = {str(n).lower() for n in names if n}
    if not wanted:
        return []
    try:
        return [p for p in config.get_projects(repo) if p.name.lower() in wanted]
    except config.ConfigError:
        return []


def require_work(repo, names, what, identity=None):
    """Raise LitterboxError unless the current user may work on parts in the projects with these names."""
    projects = [p for p in projects_named(repo, names) if p.restricted]
    if not projects:
        return
    identity, legacy = (identity, False) if identity is not None else current(repo)
    legacy = legacy or identity.state == team_identity.LEGACY
    for project in projects:
        if not may_work(identity.person if identity.state == team_identity.OK else None, project, legacy):
            raise LitterboxError(refusal(identity.directory, project, what))


def require_edit(repo, project):
    """Raise LitterboxError unless the current user may change this project."""
    identity, legacy = current(repo)
    person = identity.person if identity.state == team_identity.OK else None
    if not may_edit(person, project, legacy):
        raise LitterboxError(f"Only an Admin or {lead_name(identity.directory, project) or 'its Lead'} can change "
                             f"project {project.name}.")
    return identity


SIGNING = "signoff"                     # the permission a workflow's responses use: may_sign, not may_work


def projects_of(repo, pns):
    """The restricted projects these parts are in: a part is in the project whose block holds its number (documents
    are in none)."""
    try:
        projects = [p for p in config.get_projects(repo) if p.restricted]
    except config.ConfigError:
        return []
    found = []
    for pn in pns:
        base = getattr(pn, "base", None)
        project = next((p for p in projects if base is not None and p.contains(base)), None)
        if project is not None and project not in found:
            found.append(project)
    return found


def require_parts(repo, pns, action, identity=None):
    """Raise LitterboxError unless the current user may do `action` (a permission name: 'signoff' asks may_sign,
    the rest may_work) to these parts. Parts in no restricted project always pass."""
    projects = projects_of(repo, pns)
    if not projects:
        return
    if identity is None:
        identity, legacy = current(repo)
        if legacy:
            return
    if identity.state == team_identity.LEGACY:
        return
    person = identity.person if identity.state == team_identity.OK else None
    for project in projects:
        allowed = may_sign(identity.directory, person, project) if action == SIGNING else may_work(person, project)
        if not allowed:
            pn = next(pn for pn in pns if getattr(pn, "base", None) is not None and project.contains(pn.base))
            what = f"sign for {pn}" if action == SIGNING else f"change {pn}"
            raise LitterboxError(refusal(identity.directory, project, what))


def require_signers(repo, pns, person_ids, directory):
    """Raise LitterboxError unless every one of these people may sign for these parts."""
    projects = projects_of(repo, pns)
    if not projects or directory is None:
        return
    for person_id in dict.fromkeys(person_ids):
        person = directory.get(person_id)
        for project in projects:
            if not may_sign(directory, person, project):
                name = person.name if person else person_id
                raise LitterboxError(f"{name} can't sign for parts in project {project.name}: it is restricted to "
                                     "its members.")


def usable_here(repo, projects):
    """The projects New Part, New Assembly and Import offer the current user (usable(), for whoever is signed in)."""
    try:
        identity, legacy = current(repo)
    except LitterboxError:
        return [p for p in projects if not p.restricted]
    person = identity.person if identity.state == team_identity.OK else None
    return usable(person, projects, legacy)


def signing_directory(repo, directory, pns):
    """The team, less the people who may not sign for these parts (their projects are restricted): what a window
    offers as signers."""
    projects = projects_of(repo, pns)
    if directory is None or not projects:
        return directory
    keep = [p for p in directory.people if all(may_sign(directory, p, project) for project in projects)]
    return replace(directory, people=keep)


def refused(repo, items):
    """{pn: why} for the parts the current user may not do these actions to: `items` is [(pn, permission)]. The
    settings and who you are are read once, for a whole batch."""
    projects = projects_of(repo, [pn for pn, _action in items])
    if not projects:
        return {}
    identity, legacy = current(repo)
    if legacy:
        return {}
    found = {}
    for pn, action in items:
        try:
            require_parts(repo, [pn], action, identity)
        except LitterboxError as e:
            found[pn] = str(e)
    return found
