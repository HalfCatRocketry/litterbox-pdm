"""
journal.py - a small JSON note in the vault's .git folder about an operation that is under way.

The importer and Revise write one before they change the vault and delete it when they are done. If Litterbox
stops half way, the note says what to put back (see importing/importer.recover and parts/revise.recover). This
file only reads and writes the note; what goes in it, and checking what it says, is up to each caller.
"""

import json
from pathlib import Path


def path(repo, name):
    """Where the journal called `name` lives: inside .git, so git never sees it."""
    return Path(repo) / ".git" / name


def write(repo, name, data):
    """Save `data` (a dict) as the journal, all at once: a half-written journal is never left behind."""
    target = path(repo, name)
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
    tmp.replace(target)


def load(repo, name, version):
    """The journal's data, or None if there is none. Raises OSError or ValueError if it can't be read, or if it was
    written with a different `version`."""
    target = path(repo, name)
    if not target.exists():
        return None
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != version:
        raise ValueError("unknown version")
    return data


def clear(repo, name):
    """Delete the journal, if there is one."""
    try:
        path(repo, name).unlink()
    except FileNotFoundError:
        pass
