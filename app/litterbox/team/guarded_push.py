"""
guarded_push.py - every upload Litterbox makes: first check that the vault's latest team list still lets you
upload (team_store.check_before_push), then push, syncing and retrying if someone else pushed first
(git/remote.push_with_retry).
"""

from litterbox.git import remote
from litterbox.team import team_store


def push(repo, attempts=3):
    """Check the team list, then push. Raises PeopleError (nothing uploaded) if you may no longer upload."""
    team_store.check_before_push(repo)
    remote.push_with_retry(repo, attempts)
