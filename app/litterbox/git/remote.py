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
    """Sync then push. If someone else pushed first, sync again and retry. (Litterbox pushes through
    team/guarded_push.push, which first checks that the team list still lets you upload.)"""
    for attempt in range(1, attempts + 1):
        pull(repo)
        try:
            runner.run(["git", "push"], repo)
            return
        except LitterboxError:
            if attempt == attempts:
                raise
            diagnostics.LOG("Push was rejected. Syncing and trying again...")
