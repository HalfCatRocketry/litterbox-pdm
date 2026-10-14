"""
remote.py - getting the latest from the vault's remote, and pushing to it.

A pull tells util/file_snapshot first, because git's autostash changes file times.
"""

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import runner
from litterbox.util import file_snapshot


def pull(repo):
    file_snapshot.before_pull(repo)
    try:
        runner.run(["git", "pull", "--rebase", "--autostash"], repo)
    finally:
        file_snapshot.after_pull(repo)


def push_with_retry(repo, attempts=3):
    """Sync then push. If someone else pushed first, sync again and retry.
    First checks that the vault's latest team list still lets you upload."""
    from litterbox.team import team_store
    team_store.check_before_push(repo)
    for attempt in range(1, attempts + 1):
        pull(repo)
        try:
            runner.run(["git", "push"], repo)
            return
        except LitterboxError:
            if attempt == attempts:
                raise
            diagnostics.LOG("Push was rejected. Syncing and trying again...")
