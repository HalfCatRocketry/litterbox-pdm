"""
guarded_push.py - every upload Litterbox makes: sync, then push, syncing and retrying if someone else pushed first
(git/remote.push_with_retry). After every sync, before pushing, two checks stop the upload: the vault's latest team
list must still let you upload (team_store.check_before_push), and this Litterbox must still be allowed to work in
the vault (vault/compatibility.py: someone may have raised its format or min_litterbox_version meanwhile). Both read
what the sync has just fetched, so they ask the server nothing more.
"""

from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.team import team_store
from litterbox.vault import compatibility
from litterbox.vault import config


def still_compatible(repo):
    """Raise LitterboxError if the vault, as just synced, needs a newer Litterbox."""
    try:
        compatibility.check_compatible(repo)
    except config.ConfigError as e:
        raise LitterboxError(f"Nothing was uploaded. {e}") from None


def push(repo, attempts=3):
    """Sync, check, push. Raises PeopleError (nothing uploaded) if you may no longer upload, and LitterboxError
    (nothing uploaded) if the vault now needs a newer Litterbox. Your commits stay on your computer either way."""
    def checks():
        team_store.check_before_push(repo, fetch=False)        # the sync has just fetched
        still_compatible(repo)
    remote.push_with_retry(repo, attempts, after_sync=checks)
