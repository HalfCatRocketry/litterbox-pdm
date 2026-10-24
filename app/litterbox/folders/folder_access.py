"""
folder_access.py - who sees and who changes which folders (Home in the main window):

    Personal    yours alone, on this computer: always yours to change.
    Team        everyone sees them; Admins, the Owner and holders of a role ticked "Team folders" (Team > Roles...,
                team_model.Directory.folder_roles) change them.
    Projects    a folder for each project you are the Lead or a member of (Admins and the Owner see every project's
                but a hidden one's, unless they are in it); its Lead, Admins and the Owner change it, and its members
                too unless the project says only its Lead (core/projects.py, lead_only_folders).

A vault without a team file lets everybody do everything, as everywhere else. Like every Litterbox permission it is
process control: check_upload refuses an upload of folder changes you may not make (team/guarded_push.py), but git
by hand can still change them.
"""

from litterbox.errors import LitterboxError
from litterbox.team import team_identity
from litterbox.team import team_model

PERSONAL, TEAM, PROJECT = "personal", "team", "project"


class FoldersRefused(LitterboxError):
    """An upload refused because it changes folders the person may not change (nothing was uploaded)."""


def _legacy(identity):
    return identity is None or identity.state == team_identity.LEGACY


def _admin(person):
    return bool(person and person.active and person.access in (team_model.OWNER, team_model.ADMIN))


def shown_projects(identity, projects):
    """The projects whose folders Home shows you."""
    if _legacy(identity):
        return [p for p in projects if not p.hidden]
    person = identity.person if identity.state == team_identity.OK else None
    if person is None or not person.active:
        return []
    return [p for p in projects if p.lead == person.id or person.id in p.members
            or (_admin(person) and not p.hidden)]


def may_change(identity, scope, project=None):
    """(True, "") or (False, why not) for changing a tree's folders: `scope` is PERSONAL, TEAM or PROJECT (with the
    project, a core/projects.Project)."""
    if scope == PERSONAL or _legacy(identity):
        return True, ""
    if identity.state != team_identity.OK:
        return False, identity.message()
    person, directory = identity.person, identity.directory
    if scope == TEAM:
        if directory is not None and directory.may_change_team_folders(person):
            return True, ""
        return False, ("Only Admins, the Owner and people with a role allowed to (Team > Roles...) change the "
                       "Team folders.")
    if project is None:
        return False, "That project isn't in this vault any more."
    if _admin(person) or person.id == project.lead:
        return True, ""
    if person.id in project.members and not project.lead_only_folders:
        return True, ""
    if person.id in project.members:
        return False, f"Only {project.name}'s Lead changes its folders."
    return False, f"Only {project.name}'s Lead and members change its folders."


def check_upload(changes, identity, projects):
    """Problems with uploading these folder changes ([(scope, project name)]) as this person: [] if none."""
    by_name = {p.name.lower(): p for p in projects}
    problems = []
    for scope, name in changes:
        project = by_name.get(str(name or "").lower()) if scope == PROJECT else None
        allowed, why = may_change(identity, scope, project)
        if not allowed and why not in problems:
            problems.append(why)
    return problems
