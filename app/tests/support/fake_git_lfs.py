#!/usr/bin/env python3
"""
A stand-in for git-lfs, used by the tests that run real git (tests/support/vault_fixture.py).

Locks (`git lfs lock / unlock / locks`) are kept in a JSON file (env LFS_STORE) shared by every simulated user,
and the current user is taken from env LFS_USER. Like the real thing, it:
  * refuses a lock that someone else already holds
  * makes a file writable when you lock it and read-only when you unlock it
  * refuses to unlock a file that has uncommitted changes (unless --force)
  * fails every lock command if .git/lfs/lockcache.db is damaged (a test writes "broken" into it)

Vaults that store CAD files through LFS (env LFS_OBJECTS, standing in for the server) also get the filters: `clean`
stores a file and gives git a pointer, `smudge` turns a pointer back into the file (or leaves it, with --skip or
GIT_LFS_SKIP_SMUDGE=1), `pull [--include=a,b]` downloads pointers, and `install --local [--skip-smudge]` sets the
filters up.
"""

import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone

STORE = os.environ["LFS_STORE"]
USER = os.environ.get("LFS_USER", "")
OBJECTS = os.environ.get("LFS_OBJECTS", "")
POINTER = b"version https://git-lfs.github.com/spec/v1"


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


def pointer(oid, size):
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode()


def content(pointer_data):
    oid = pointer_data.split(b"oid sha256:")[1].split(b"\n")[0].decode()
    with open(os.path.join(OBJECTS, oid), "rb") as f:
        return f.read()


args = sys.argv[1:]
command = args[0] if args else ""
paths = [a.replace("\\", "/") for a in args[1:] if not a.startswith("--")]

if command in ("lock", "unlock", "locks"):
    try:                            # Litterbox runs several lock commands at once; a real server handles each as one step
        import fcntl
        _guard = open(STORE + ".guard", "w")
        fcntl.flock(_guard, fcntl.LOCK_EX)      # released when this process ends (only lock commands take it, so a
    except ImportError:                         # filter git runs from inside `unlock` never waits for it)
        pass                        # not Linux: the tests that use this fake don't run there

    # Like real git-lfs, every lock command first reads the lock cache; a damaged one makes it fail.
    CACHE = os.path.join(".git", "lfs", "lockcache.db")
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            if f.read().startswith(b"broken"):
                fail("Unable to create lock system: lock cache initialization: problem reading updated key/value "
                     f"data from {os.path.abspath(CACHE)}: gob: bad data: field numbers out of bounds")

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

elif command == "install" and OBJECTS and "--local" in args:
    skip = " --skip" if "--skip-smudge" in args else ""
    for key, value in (("filter.lfs.clean", "git-lfs clean -- %f"), ("filter.lfs.smudge", f"git-lfs smudge{skip} -- %f"),
                       ("filter.lfs.required", "true")):
        subprocess.run(["git", "config", "--local", key, value], check=True)
    print("Updated Git hooks. (fake)")

elif command == "install":
    print("Updated Git hooks. (fake)")

elif command == "clean":                    # git add: the file goes in as a pointer, its content to the store
    data = sys.stdin.buffer.read()
    if not data.startswith(POINTER):
        oid = hashlib.sha256(data).hexdigest()
        os.makedirs(OBJECTS, exist_ok=True)
        with open(os.path.join(OBJECTS, oid), "wb") as f:
            f.write(data)
        data = pointer(oid, len(data))
    sys.stdout.buffer.write(data)

elif command == "smudge":                   # git checkout: the pointer becomes the file, unless told to skip
    data = sys.stdin.buffer.read()
    if data.startswith(POINTER) and "--skip" not in args and os.environ.get("GIT_LFS_SKIP_SMUDGE") != "1":
        data = content(data)
    sys.stdout.buffer.write(data)

elif command == "pull":                     # download pointers: the ones --include names, or all of them
    wanted = None
    for a in args[1:]:
        if a.startswith("--include="):
            wanted = set(a.split("=", 1)[1].split(","))
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    for path in tracked:
        if (wanted is None or path in wanted) and os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            if data.startswith(POINTER):
                tmp = path + ".lfs-download"
                with open(tmp, "wb") as f:
                    f.write(content(data))
                os.replace(tmp, path)       # a new file, read-only like git-lfs leaves a lockable file
                os.chmod(path, 0o444)

else:
    fail(f"fake git-lfs: unsupported command '{command}'")
