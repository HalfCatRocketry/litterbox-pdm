"""
guarded_push.py - every upload Litterbox makes: sync, then push, syncing and retrying if someone else pushed first
(git/remote.push_with_retry). After every sync, before pushing, three checks stop the upload: the vault's latest team
list must still let you upload (team_store.check_before_push), this Litterbox must still be allowed to work in
the vault (vault/compatibility.py: someone may have raised its format or min_litterbox_version meanwhile), and only
an Admin or the Owner may upload a change to the team's Toolbox (the vault's toolbox/ folder, vault/toolbox_admin.py).
They read what the sync has just fetched, so they ask the server nothing more.
"""

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.git import repository
from litterbox.team import team_identity
from litterbox.team import team_store
from litterbox.vault import compatibility
from litterbox.vault import config


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


def push(repo, attempts=3):
    """Sync, check, push. Raises PeopleError (nothing uploaded) if you may no longer upload, and LitterboxError
    (nothing uploaded) if the vault now needs a newer Litterbox. Your commits stay on your computer either way."""
    def checks():
        team_store.check_before_push(repo, fetch=False)        # the sync has just fetched
        still_compatible(repo)
        toolbox_allowed(repo)
    remote.push_with_retry(repo, attempts, after_sync=checks)
