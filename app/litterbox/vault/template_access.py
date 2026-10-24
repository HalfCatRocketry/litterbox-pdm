"""
template_access.py - who changes the vault's SolidWorks templates (Team > Templates...): the org's, Admins and the
Owner; a project's, its Lead too. Everyone uses them.

A vault without a team file lets everybody do everything, as everywhere else. Like every Litterbox permission it is
process control: check_upload refuses an upload of template changes you may not make (team/guarded_push.py), but git
by hand can still change them.
"""

from litterbox.core import projects as project_rules
from litterbox.core import template_rules
from litterbox.team import team_identity
from litterbox.team import team_model


def _admin(person):
    return bool(person and person.active and person.access in (team_model.OWNER, team_model.ADMIN))


def may_change(identity, project=None):
    """(True, "") or (False, why not) for changing the org's templates (project None) or a project's (a
    core/projects.Project)."""
    if identity is None or identity.state == team_identity.LEGACY:
        return True, ""
    if identity.state != team_identity.OK:
        return False, identity.message()
    person = identity.person
    if _admin(person):
        return True, ""
    if project is None:
        return False, "Only Admins and the Owner change the org's templates."
    if person is not None and person.active and person.id == project.lead:
        return True, ""
    return False, f"Only {project.name}'s Lead, Admins and the Owner change its templates."


def check_upload(owners, identity, projects):
    """Problems with uploading changes to these owners' templates ({project name or template_rules.ORG}) as this
    person: [] if none. A project that isn't in the vault any more (renamed or deleted) isn't anyone's to guard."""
    problems = []
    for owner in sorted(owners):
        if owner == template_rules.ORG:
            allowed, why = may_change(identity)
        else:
            try:
                project = project_rules.find(owner, projects)
            except project_rules.ProjectError:
                continue
            allowed, why = may_change(identity, project)
        if not allowed and why not in problems:
            problems.append(why)
    return problems
