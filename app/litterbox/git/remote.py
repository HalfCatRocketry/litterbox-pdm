"""
remote.py - getting the latest from the vault's remote, and pushing to it.

A pull tells util/file_snapshot first, because git's autostash changes file times. In a vault that downloads on
demand, a pull leaves every changed CAD file as a pointer, so the files that were on disk before the pull are
downloaded again: what you had stays downloaded, and nothing else is.
"""

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import runner
from litterbox.util import file_snapshot


def pull(repo):
    on_disk = lfs_download.downloaded_cad_files(repo)
    file_snapshot.before_pull(repo)
    try:
        runner.run(["git", "pull", "--rebase", "--autostash"], repo)
        try:
            lfs_download.download(repo, on_disk, "updated files you already had")
        except LitterboxError as e:             # the pull itself worked: say so, and carry on
            diagnostics.LOG(f"WARNING: some files you had could not be downloaded again; they show as not "
                            f"downloaded. {e}")
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
