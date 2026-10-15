#!/usr/bin/env python3
"""
A stand-in for `git lfs lock / unlock / locks`, used ONLY by test_engine_flow.py.

Locks are kept in a JSON file (env LFS_STORE) shared by every simulated user,
and the current user is taken from env LFS_USER. Like the real thing, it:
  * refuses a lock that someone else already holds
  * makes a file writable when you lock it and read-only when you unlock it
  * refuses to unlock a file that has uncommitted changes (unless --force)
"""

import json
import os
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone

STORE = os.environ["LFS_STORE"]
USER = os.environ["LFS_USER"]

try:                                # Litterbox runs several lock commands at once; a real server handles each as one step
    import fcntl
    _guard = open(STORE + ".guard", "w")
    fcntl.flock(_guard, fcntl.LOCK_EX)          # released when this process ends
except ImportError:                 # not Linux: the tests that use this fake don't run there
    pass


def load():
    try:
        with open(STORE) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save(locks):
    with open(STORE, "w") as f:
        json.dump(locks, f)


def fail(message):
    sys.stderr.write(message + "\n")
    sys.exit(2)


args = sys.argv[1:]
command = args[0] if args else ""
paths = [a.replace("\\", "/") for a in args[1:] if not a.startswith("--")]

# Like real git-lfs, every lock command first reads the lock cache; a damaged one (a test writes "broken" into it)
# makes the command fail with the message git-lfs gives.
CACHE = os.path.join(".git", "lfs", "lockcache.db")
if command in ("lock", "unlock", "locks") and os.path.exists(CACHE):
    with open(CACHE, "rb") as f:
        if f.read().startswith(b"broken"):
            fail("Unable to create lock system: lock cache initialization: problem reading updated key/value data "
                 f"from {os.path.abspath(CACHE)}: gob: bad data: field numbers out of bounds")

if command == "lock":
    path = paths[0]
    locks = load()
    for lock in locks:
        if lock["path"] == path:
            fail(f"Lock failed: {path} already locked by {lock['owner']['name']}")
    if not os.path.exists(path):
        fail(f"Lock failed: {path} does not exist")
    locks.append({
        "id": uuid.uuid4().hex, "path": path, "owner": {"name": USER},
        "locked_at": datetime.now(timezone.utc).isoformat(),
    })
    save(locks)
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
    print(f"Locked {path}")

elif command == "unlock":
    path = paths[0]
    force = "--force" in args
    locks = load()
    match = next((lock for lock in locks if lock["path"] == path), None)
    if match is None:
        fail(f"Unable to unlock: no lock on {path}")
    if match["owner"]["name"] != USER and not force:
        fail(f"Unable to unlock: {path} is locked by {match['owner']['name']}")
    if not force:
        status = subprocess.run(["git", "status", "--porcelain", "--", path],
                                capture_output=True, text=True).stdout.strip()
        if status:
            fail(f"Cannot unlock file with uncommitted changes: {path}")
    save([lock for lock in locks if lock["path"] != path])
    if os.path.exists(path):
        os.chmod(path, os.stat(path).st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    print(f"Unlocked {path}")

elif command == "locks":
    locks = load()
    if "--verify" in args:
        print(json.dumps({
            "ours": [lock for lock in locks if lock["owner"]["name"] == USER],
            "theirs": [lock for lock in locks if lock["owner"]["name"] != USER],
        }))
    else:
        print(json.dumps(locks))

elif command == "version":
    print("git-lfs/3.0.0 (fake)")

elif command == "install":
    print("Updated Git hooks. (fake)")

else:
    fail(f"fake git-lfs: unsupported command '{command}'")
