"""
guarded_push.py - every upload Litterbox makes: first check that the vault's latest team list still lets you
upload (team_store.check_before_push), then push, syncing and retrying if someone else pushed first
(git/remote.push_with_retry). After every sync, before pushing, it checks that this Litterbox may still work in the
vault (vault/compatibility.py): if someone raised its format or min_litterbox_version meanwhile, nothing is
uploaded. That check reads one small local file, so it costs about a millisecond.
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
    """Check the team list, then push. Raises PeopleError (nothing uploaded) if you may no longer upload, and
    LitterboxError (nothing uploaded) if the vault now needs a newer Litterbox."""
    team_store.check_before_push(repo)
    remote.push_with_retry(repo, attempts, after_sync=lambda: still_compatible(repo))
