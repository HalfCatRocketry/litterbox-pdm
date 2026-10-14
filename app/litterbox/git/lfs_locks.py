"""
lfs_locks.py - Git LFS locks: reading them, taking them and giving them back.

"Check out" means taking the LFS lock. git-lfs locks one file per command, so several commands run at the same
time (LOCK_WORKERS).
"""

import json
from concurrent.futures import ThreadPoolExecutor

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import runner


def get_locks(repo, strict=False):
    """Return {lowercase_path: ("you" or "other", owner_name)} for every lock.

    strict=False: if the lock list can't be read (offline?), warn and return {}.
                  Fine for just displaying things.
    strict=True:  raise LitterboxError instead. Anything that unlocks or changes
                  files uses this, so a network problem can never be mistaken
                  for "nothing is locked".
    """
    try:
        out = runner.run(["git", "lfs", "locks", "--verify", "--json"], repo, quiet=True)
        data = json.loads(out) if out else {}
    except (LitterboxError, json.JSONDecodeError) as e:
        if strict:
            raise LitterboxError(f"Could not read the lock list. Are you online?\n\n{e}")
        diagnostics.LOG(f"WARNING: could not read locks (offline?). {e}")
        return {}

    locks = {}
    if isinstance(data, dict):  # the --verify format
        for lock in data.get("ours", []):
            locks[lock["path"].lower()] = ("you", lock.get("owner", {}).get("name", "you"))
        for lock in data.get("theirs", []):
            locks[lock["path"].lower()] = ("other", lock.get("owner", {}).get("name", "someone"))
    else:  # plain list format (no ours/theirs information)
        for lock in data:
            locks[lock["path"].lower()] = ("other", lock.get("owner", {}).get("name", "someone"))
    return locks


def is_mine(locks, path):
    return locks.get(path.lower(), ("", ""))[0] == "you"


def lock(repo, path, label):
    """Lock one file. `label` is the PN, used in the error message."""
    try:
        runner.run(["git", "lfs", "lock", path], repo)
    except LitterboxError:
        lock = get_locks(repo).get(path.lower())
        if lock and lock[0] == "you":
            return                      # already ours, nothing to do
        if lock:
            raise LitterboxError(f"{label} is already checked out by {lock[1]}.")
        raise


LOCK_WORKERS = 6        # git-lfs locks one file per command, so several commands run at the same time


def _parallel(func, items):
    """[(result, error)] for func(item) on each item, several at a time. Only LitterboxError is caught."""
    items = list(items)

    def call(item):
        try:
            return func(item), None
        except LitterboxError as e:
            return None, e

    if len(items) <= 1:
        return [call(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(LOCK_WORKERS, len(items))) as pool:
        return list(pool.map(call, items))


def lock_many(repo, wanted):
    """Lock several files at once. `wanted` is [(path, label)]; returns {path: None, or the error}.

    Somebody else's lock is reported as it is. Any other failure (a busy server, say) is tried once more, one at
    a time, before it counts."""
    results = _parallel(lambda item: lock(repo, item[0], item[1]), wanted)
    outcome = {}
    for (path, label), (_value, error) in zip(wanted, results):
        if error is not None and "already checked out" not in str(error):
            try:
                lock(repo, path, label)
                error = None
            except LitterboxError as e:
                error = e
        outcome[path] = error
    return outcome


def unlock_mine(repo, paths):
    """Unlock every one of these paths that you hold. Returns [(path, error), ...] for failures."""
    locks = get_locks(repo, strict=True)
    mine = [path for path in paths if is_mine(locks, path)]
    results = _parallel(lambda path: runner.run(["git", "lfs", "unlock", path], repo), mine)
    return [(path, str(error)) for path, (_value, error) in zip(mine, results) if error is not None]


def force_unlock_quietly(repo, paths):
    """Used when rolling back after an error: release locks, never raise."""
    paths = list(paths)
    for path, (_value, error) in zip(paths, _parallel(
            lambda path: runner.run(["git", "lfs", "unlock", "--force", path], repo), paths)):
        if error is not None:
            diagnostics.LOG(f"WARNING: could not release the lock on {path}: {error}")


def unlock_failure_message(failed):
    lines = "\n".join(f"  {path}: {err.splitlines()[-1] if err else ''}" for path, err in failed)
    return ("Your changes are saved in the vault, but some files could not be unlocked:\n"
            f"{lines}\n\nClick Check In again to retry the unlock "
            "(if it says no changes were detected, choose Continue).")
