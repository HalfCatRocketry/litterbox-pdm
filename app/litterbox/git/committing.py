"""
committing.py - making commits from a list of paths, and putting files back.

Paths go through a temporary pathspec file, so a commit of hundreds of files never builds a command line too long
for Windows.
"""

import os
import tempfile

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.git import runner


def write_pathspec(paths):
    """A list of paths in a temporary file, for git's --pathspec-from-file (avoids very long command lines).
    Returns the file's path; the caller deletes it."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8", newline="\n")
    with handle:
        handle.write("\n".join(paths) + "\n")
    return handle.name


def commit_paths(repo, subject, body, paths):
    """ONE commit of exactly these paths, however many there are (a list in a file, so it is never split up)."""
    command = ["git", "commit", "-m", subject] + (["-m", body] if body else [])
    pathspec = write_pathspec(paths)
    try:
        runner.run(command + [f"--pathspec-from-file={pathspec}"], repo)
    finally:
        try:
            os.unlink(pathspec)
        except OSError:
            pass


def discard_quietly(repo, paths):
    """Throw away uncommitted changes to tracked files, never raise."""
    try:
        runner.run_chunked(["git", "restore"], paths, repo)
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not restore {', '.join(paths)}: {e}")
