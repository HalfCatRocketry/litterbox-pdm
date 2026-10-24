"""
guarded_push.py - every upload Litterbox makes: sync, then push, syncing and retrying if someone else pushed first
(git/remote.push_with_retry). After every sync, before pushing, five checks stop the upload: the vault's latest team
list must still let you upload (team_store.check_before_push), this Litterbox must still be allowed to work in
the vault (vault/compatibility.py: someone may have raised its format or min_litterbox_version meanwhile), only
an Admin or the Owner may upload a change to the team's Toolbox (the vault's toolbox/ folder, vault/toolbox_admin.py),
changes to the Team and project folders must be ones you may make (folders/folder_access.py), and so must changes
to the org's and projects' SolidWorks templates (vault/template_access.py).
They read what the sync has just fetched, so they ask the server nothing more.
"""

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.folders import folder_access
from litterbox.folders import folder_store
from litterbox.git import remote
from litterbox.git import repository
from litterbox.team import team_identity
from litterbox.team import team_store
from litterbox.vault import compatibility
from litterbox.vault import config
from litterbox.vault import template_access
from litterbox.vault import template_store


def still_compatible(repo):
    """Raise LitterboxError if the vault, as just synced, needs a newer Litterbox."""
    try:
        compatibility.check_compatible(repo)
    except config.ConfigError as e:
        raise LitterboxError(f"Nothing was uploaded. {e}") from None


def toolbox_allowed(repo):
    """Raise LitterboxError (nothing uploaded) if your commits change the team's Toolbox and you may not."""
    folder = layout.TOOLBOX_DIR_NAME.lower() + "/"
    if not any(path.lower().startswith(folder) for path in repository.paths_changed_in(repo, repository.UNPUSHED)):
        return
    allowed, _why = team_identity.current(repo, probe=False).allows("manage_toolbox")
    if not allowed:
        raise LitterboxError(f"Nothing was uploaded: your changes include files in the team's Toolbox "
                             f"({layout.TOOLBOX_DIR_NAME}/), which only an Admin or the Owner may change.")


def folders_allowed(repo):
    """Raise LitterboxError (nothing uploaded) if your commits change Team or project folders you may not change."""
    changes = folder_store.unpushed_changes(repo, repository.paths_changed_in(repo, repository.UNPUSHED))
    if not changes:
        return
    who = team_identity.current(repo, probe=False)
    if who.state == team_identity.UNVERIFIED:                  # not known on this computer yet: ask the host once
        who = team_identity.current(repo)
    problems = folder_access.check_upload(changes, who, config.get_projects(repo))
    if problems:
        raise folder_access.FoldersRefused("Nothing was uploaded: your changes include folder changes you may not "
                                           "make. " + " ".join(problems))


def templates_allowed(repo):
    """Raise LitterboxError (nothing uploaded) if your commits change the org's or a project's templates and you may
    not change them."""
    prefix = layout.TEMPLATES_DIR_NAME.lower() + "/"
    changed = [p for p in repository.paths_changed_in(repo, repository.UNPUSHED) if p.lower().startswith(prefix)]
    if not changed:
        return
    before = template_store.parse(repository.quiet_output(repo, "show", f"@{{u}}:{layout.TEMPLATES_INDEX}"))
    after = template_store.parse(repository.quiet_output(repo, "show", f"HEAD:{layout.TEMPLATES_INDEX}"))
    owners = template_store.changed_owners(before, after, changed)
    if not owners:
        return
    who = team_identity.current(repo, probe=False)
    if who.state == team_identity.UNVERIFIED:                  # not known on this computer yet: ask the host once
        who = team_identity.current(repo)
    problems = template_access.check_upload(owners, who, config.get_projects(repo))
    if problems:
        raise LitterboxError("Nothing was uploaded: your changes include template changes you may not make. "
                             + " ".join(problems))


def push(repo, attempts=3):
    """Sync, check, push. Raises PeopleError (nothing uploaded) if you may no longer upload, and LitterboxError
    (nothing uploaded) if the vault now needs a newer Litterbox. Your commits stay on your computer either way."""
    def checks():
        team_store.check_before_push(repo, fetch=False)        # the sync has just fetched
        still_compatible(repo)
        toolbox_allowed(repo)
        folders_allowed(repo)
        templates_allowed(repo)
    remote.push_with_retry(repo, attempts, after_sync=checks)
