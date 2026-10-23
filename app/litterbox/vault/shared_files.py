"""
shared_files.py - changing the vault's shared settings files (.litterbox/config.yaml, people.yaml, workflows.yaml,
document_types.yaml) for everyone: lock, get the latest, change, commit, upload, unlock. If any step fails, every file
is put back as it was and the lock is given back, so a half-made change is never left behind or uploaded.

    shared_files.edit(repo, [layout.WORKFLOWS_FILE, layout.CONFIG_PATH], "the workflows file", change)

Each caller checks the user's permission first, and its change() does the rest: read, change and save the files.
"""

from pathlib import Path

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.team import guarded_push


def edit(repo, files, label, change):
    """Change shared files for everyone. `files` are the vault-relative paths change() may write; the first is the
    one locked (when git tracks it), so two people can't change them at once. `label` names it in the lock error.

    change() runs after the latest is fetched and returns (paths to commit, commit message, result); nothing is
    committed when the paths are empty. Returns the result."""
    rel = files[0]
    locked = repository.in_index(repo, rel)
    if locked:
        lfs_locks.lock(repo, rel, label)
    saved, committed = {}, False
    try:
        remote.pull(repo)
        saved = {path: _snapshot(repo, path) for path in files}
        paths, message, result = change()
        if paths:
            runner.run(["git", "add", "--"] + list(paths), repo)
            runner.run(["git", "commit", "-m", message, "--"] + list(paths), repo)
            committed = True
            guarded_push.push(repo)
    except BaseException:
        _put_back(repo, rel, saved, committed)
        if locked:
            lfs_locks.force_unlock_quietly(repo, [rel])
        raise
    if locked:
        failed = lfs_locks.unlock_mine(repo, [rel])
        if failed:
            raise LitterboxError(lfs_locks.unlock_failure_message(failed))
    return result


def _snapshot(repo, path):
    """(does git track it, its bytes or None): how to put a file back."""
    full = Path(repo) / path
    return repository.in_index(repo, path), (full.read_bytes() if full.is_file() else None)


def _put_back(repo, rel, saved, committed):
    """Undo edit(): drop its commit, then return each file to how it was after the pull (a tracked file from git, an
    untracked one from the bytes kept). Never raises: what can't be undone is logged."""
    try:
        if committed:
            runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
        for path, (tracked, before) in saved.items():
            if tracked:
                runner.run(["git", "restore", "--staged", "--worktree", "--", path], repo)
                continue
            runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", path], repo, quiet=True)
            full = Path(repo) / path
            if before is None:
                full.unlink(missing_ok=True)
            else:
                full.write_bytes(before)                    # an untracked file of theirs
    except (LitterboxError, OSError) as e:
        diagnostics.LOG(f"WARNING: could not fully undo the change to {rel}: {e}")
