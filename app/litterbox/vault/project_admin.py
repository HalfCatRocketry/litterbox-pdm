"""
project_admin.py - adding, changing and deleting projects. Adding one is for Admins and the Owner (the permission
is "manage_settings"), or for anyone on the team when the org allows it (core/project_settings.py); whoever adds
one becomes its Lead unless they choose another. Changing its digits and deleting it is for Admins and the Owner;
its Lead may also change its name, Lead, members, Restrict and Hide (team/project_access.py may_edit). Starting
digits fewer than the org's minimum are refused, unless an Admin or the Owner was warned and goes ahead (short_ok).

A project is a block of part numbers (core/projects.py), and each part's record says its project. Changing a
project's name or digits, or deleting it, therefore also changes the records of the parts that join it, leave it or
are renamed, in the same upload as the settings file. Every one of those records is locked first, so the change is
refused, naming the parts, if any of them is checked out. After a change, a part is in the project exactly when its
number is in the project's block.

    project_admin.add_project(repo, "Rover", "12")
    project_admin.plan_change(repo, "Rover", "Rover", "123")    # what would change (shown before asking)
    project_admin.edit_project(repo, "Rover", "Rover", "123")
    project_admin.edit_project(repo, "Rover", "Rover", "12", team={"lead": "alex", "members": ["bea"],
                                                                   "restricted": True, "hidden": False})
    project_admin.delete_project(repo, "Rover")
"""

from dataclasses import dataclass, field

from litterbox import diagnostics
from litterbox import layout
from litterbox.core import project_settings
from litterbox.core import projects as project_rules
from litterbox.errors import LitterboxError
from litterbox.folders import folder_access
from litterbox.folders import folder_store
from litterbox.git import lfs_locks
from litterbox.git import remote
from litterbox.git import repository
from litterbox.parts import batch_core
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import project_access
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.vault import settings_admin
from litterbox.vault import template_admin


@dataclass
class ProjectChange:
    """What changing (or deleting, `new` None) a project does."""
    old: project_rules.Project
    new: project_rules.Project = None
    projects: list = field(default_factory=list)     # every project afterwards
    updates: dict = field(default_factory=dict)      # PN -> its project afterwards ("" for none), for each record that changes
    joining: list = field(default_factory=list)      # parts that come into the project
    leaving: list = field(default_factory=list)      # parts that leave it (no project afterwards)
    renamed: list = field(default_factory=list)      # parts that stay in it under its new name
    checked_out: dict = field(default_factory=dict)  # PN -> who has it checked out, among the parts that change

    @property
    def deleting(self):
        return self.new is None


def team_of(project):
    """{lead, members, restricted, hidden, lead_only_folders} of a project, as edit_project's `team` takes them."""
    return {"lead": project.lead, "members": list(project.members), "restricted": project.restricted,
            "hidden": project.hidden, "lead_only_folders": project.lead_only_folders}


def with_team(repo, project, team):
    """The project with `team` ({lead, members, restricted, hidden}; None for none of them), checked: the Lead and
    the members must be people on the team, and the Lead switched on. Raises ProjectError."""
    team = dict(team or {})
    project = project_rules.with_team(project, team.get("lead", ""), team.get("members") or (),
                                      team.get("restricted", False), team.get("hidden", False),
                                      team.get("lead_only_folders", False))
    directory = team_store.load(repo) if (project.lead or project.members) else None
    if directory is not None:
        for person_id in ([project.lead] if project.lead else []) + list(project.members):
            person = directory.get(person_id)
            if person is None:
                raise project_rules.ProjectError(f"{person_id} isn't on the team.")
            if person_id == project.lead and not person.active:
                raise project_rules.ProjectError(f"{person.name} is switched off on the team, so can't be the Lead.")
    return project


def may_add(repo):
    """The Identity of the current user, if they may add a project now (see the top); raises LitterboxError if not."""
    if config.get_project_creators(repo) == project_settings.ANYONE:
        return team_permissions.require(repo, "edit_project")      # an active member of the team
    return team_permissions.require(repo, "manage_settings")


def is_admin(identity):
    return identity.allows("manage_settings")[0]


def check_digits(repo, prefix, identity, short_ok=False):
    """Refuse starting digits fewer than the org's minimum, unless an Admin or the Owner goes ahead (short_ok)."""
    minimum = config.get_project_min_digits(repo)
    prefix = str(prefix or "").strip()
    if project_settings.too_short(prefix, minimum) and not (short_ok and is_admin(identity)):
        raise LitterboxError(project_settings.short_text(prefix, minimum, config.get_digits(repo)[0]))


@converts_errors
def add_project(repo, name, prefix, team=None, short_ok=False):
    """Add a project, commit and upload it. It is checked again against the newest projects (someone may have just
    added one), and raises LitterboxError if the name is taken, its block overlaps another, or its digits are too few
    (check_digits). Returns the Project. Parts already in its block keep no project (the Projects window says how many
    first). `team` as with_team(); with no Lead in it, whoever adds the project is its Lead."""
    added, who = [], {}

    def may():
        who["identity"] = may_add(repo)

    def change():
        current = config.get_projects(repo)
        identity = who["identity"]
        check_digits(repo, prefix, identity, short_ok)              # the newest settings, after the pull
        chosen = dict(team or {})
        if not chosen.get("lead") and identity.person is not None:
            chosen["lead"] = identity.person.id
        try:
            project = with_team(repo, project_rules.new_project(name, prefix, current), chosen)
        except project_rules.ProjectError as e:
            raise LitterboxError(str(e)) from None
        config_write.set_values(repo, projects=current + [project])
        added.append(project)
        return f"Projects: added {project.describe()}"
    settings_admin.change_file(repo, change, check=may)
    return added[0]


@converts_errors
def parts_in_block(repo, prefix):
    """The part numbers already in the block these starting digits give (the Projects window warns about them).
    Reads your local copy only."""
    config.apply(repo)                                  # the block's size depends on the vault's digits
    low, high = project_rules.block(project_rules.check_prefix(prefix))
    return [pn for pn in record_store.list_pns(repo, config.get_org(repo)) if low <= pn.base <= high]


@converts_errors
def plan_change(repo, name, new_name=None, new_prefix=None, delete=False, locks=None, team=None):
    """What editing the project `name` (to `new_name` starting `new_prefix`, with `team` as with_team() takes it;
    None keeps its Lead, members, Restrict and Hide), or deleting it, would change, from your local copy. Raises
    LitterboxError if the new name, digits or people can't be used. `locks` defaults to the server's lock list (so
    checked_out is filled in); pass {} to leave it out."""
    config.apply(repo)
    try:
        current = config.get_projects(repo)
        old = project_rules.find(name, current)
        others = [p for p in current if p is not old]
        new = None if delete else with_team(repo, project_rules.new_project(new_name, new_prefix, others),
                                            team_of(old) if team is None else team)
    except (project_rules.ProjectError, config.ConfigError) as e:
        raise LitterboxError(str(e)) from None
    change = ProjectChange(old, new, others if delete else [new if p is old else p for p in current])
    for pn in record_store.list_pns(repo, config.get_org(repo)):
        try:
            record = record_store.load(repo, pn)
        except record_model.RegistryError as e:
            diagnostics.LOG(f"WARNING: {pn} was left out of the project change: {e}")
            continue
        was_member = record.project == old.name
        in_block = new is not None and new.contains(pn.base)
        wanted = new.name if in_block else ("" if was_member else record.project)
        if wanted == record.project:
            continue
        change.updates[pn] = wanted
        (change.renamed if in_block and was_member else change.joining if in_block else change.leaving).append(pn)
    if change.updates:
        locks = lfs_locks.get_locks(repo, strict=True) if locks is None else locks
        for pn in change.updates:
            lock = locks.get(record_store.record_relpath(pn).lower())
            if lock:
                change.checked_out[pn] = "you" if lock[0] == "you" else lock[1]
    return change


@converts_errors
def edit_project(repo, name, new_name, new_prefix, team=None, short_ok=False):
    """Change a project's name, starting digits and/or its `team` (as with_team() takes it; None keeps them), and
    the records of the parts that join, leave or are renamed, in one upload. Returns the ProjectChange done. A
    renamed project's folders (folders/folder_store.py) and templates (vault/template_admin.py) go with it."""
    change = _apply(repo, name, new_name, new_prefix, delete=False, team=team, short_ok=short_ok)
    if change.new is not None and change.new.name != change.old.name:
        _carry_folders(repo, change.old.name, change.new.name)
        _carry_templates(repo, change.old.name, change.new.name)
    return change


def _carry_folders(repo, old, new):
    """A renamed project's folders: one change that moves them to the new name (if it had any)."""
    try:
        if folder_store.tree_of(folder_store.load(repo), folder_access.PROJECT, old):
            folder_store.save_change(repo, folder_access.PROJECT, old, [{"op": folder_store.RENAMED, "name": new}],
                                     f"project {old} renamed to {new}", push=guarded_push.push)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: {new}'s folders couldn't be moved from its old name, {old}: {e}")


def _carry_templates(repo, old, new):
    """A renamed project's templates: one upload that moves them to the new name (if it had any)."""
    try:
        template_admin.rename_project(repo, old, new)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: {new}'s templates couldn't be moved from its old name, {old}: {e}")


@converts_errors
def delete_project(repo, name):
    """Delete a project: its parts have no project afterwards, and its block is free again (so New Part with no
    project may use those numbers). Returns the ProjectChange done."""
    return _apply(repo, name, delete=True)


def checked_out_text(change):
    names = "\n".join(f"  {pn} ({who})" for pn, who in sorted(change.checked_out.items())[:10])
    more = "\n  ..." if len(change.checked_out) > 10 else ""
    return (f"These parts would change project but are checked out, so nothing was changed:\n{names}{more}\n\n"
            "Ask for them to be checked in (or undone) first.")


def _message(pn, change):
    if change.deleting:
        return f"{pn}: Project {change.old.name} deleted"
    return f"{pn}: Project {change.old.name} changed to {change.new.describe()}"


def permission_for(repo, name, new_prefix=None, delete=False, short_ok=False):
    """Check the current user may make this change; returns the permission the parts' records are changed with.
    Its digits and deleting it: Admins and the Owner (new digits no fewer than the org's minimum, unless short_ok).
    The rest: them and its Lead."""
    try:
        old = project_rules.find(name, config.get_projects(repo))
    except (project_rules.ProjectError, config.ConfigError) as e:
        raise LitterboxError(str(e)) from None
    if delete or (new_prefix is not None and str(new_prefix).strip() != old.prefix):
        identity = team_permissions.require(repo, "manage_settings")
        if not delete:
            check_digits(repo, new_prefix, identity, short_ok)
        return "manage_settings"
    team_permissions.require(repo, "edit_project")              # an active member of the team
    project_access.require_edit(repo, old)
    return "edit_project"


def _what(change):
    if change.deleting:
        return f"Projects: deleted {change.old.describe()}"
    if change.new.describe() == change.old.describe():
        return f"Projects: {change.old.name} changed"            # its Lead, members, Restrict or Hide
    return f"Projects: {change.old.describe()} changed to {change.new.describe()}"


def _apply(repo, name, new_name=None, new_prefix=None, delete=False, team=None, short_ok=False):
    repository.validate_repo(repo)
    permission = permission_for(repo, name, new_prefix, delete, short_ok)
    remote.pull(repo)                                           # work out the change from the newest records
    change = plan_change(repo, name, new_name, new_prefix, delete, team=team)
    if change.checked_out:
        raise LitterboxError(checked_out_text(change))
    what = _what(change)

    def same_again():
        """The change worked out again after the latest pull: refused if someone changed the parts meanwhile."""
        again = plan_change(repo, name, new_name, new_prefix, delete, locks={}, team=team)
        if set(again.updates) != set(change.updates):
            raise LitterboxError("Parts were added to the vault while the projects were being changed. Try again.")
        try:
            config_write.set_values(repo, projects=again.projects)
        except config.ConfigError as e:
            raise LitterboxError(str(e)) from None

    def check():                                               # again, after the pull
        permission_for(repo, name, new_prefix, delete, short_ok)

    if not change.updates:                                     # no records change: the settings file alone
        settings_admin.change_file(repo, lambda: same_again() or what, check)
        return change

    path = layout.CONFIG_PATH
    tracked = repository.in_index(repo, path)
    if tracked:
        lfs_locks.lock(repo, path, "the vault settings")
    try:
        items = [(pn, permission,
                  lambda record, by, value=value: record_lifecycle.change_project(record, by, value),
                  _message(pn, change)) for pn, value in change.updates.items()]
        batch = batch_core.edit_records(repo, items, atomic=True,
                                        prepare=lambda user: same_again() or [path])
    except BaseException:
        if tracked:
            lfs_locks.force_unlock_quietly(repo, [path])
        raise
    failed = lfs_locks.unlock_mine(repo, [path]) if tracked else []
    if batch.notice or failed:
        raise LitterboxError(batch.notice or lfs_locks.unlock_failure_message(failed))
    return change
