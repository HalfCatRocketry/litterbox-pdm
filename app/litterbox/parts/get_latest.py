"""
get_latest.py - Get Latest: download what changed in the vault and
make other people's files read-only again.
"""

from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import repository
from litterbox.records.error_conversion import converts_errors
from litterbox.vault import project_visibility


@converts_errors
def get_latest(repo):
    """Download the newest changes. Returns the list of files that changed.

    If any of those files are open in SolidWorks, they need to be closed and reopened.
    """
    repository.validate_repo(repo)
    before = repository.head(repo)
    remote.pull(repo)
    project_visibility.apply(repo)                  # someone added to or taken off a hidden project
    read_only.enforce_read_only(repo)
    return repository.changed_between(repo, before, repository.head(repo))
