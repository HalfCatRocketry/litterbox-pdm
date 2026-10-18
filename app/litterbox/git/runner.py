"""
runner.py - running git (and git-lfs) commands.

Every git command Litterbox runs goes through run(), so a test can replace runner.run to watch or fake them. A
failed command raises LitterboxError; a commit with nothing in it raises NothingToSaveError.
"""

import subprocess
import time

from litterbox import diagnostics
from litterbox.errors import LitterboxError, NothingToSaveError


def _nothing_to_commit(text):
    text = text.lower()
    return "nothing to commit" in text or "no changes added to commit" in text or "nothing added to commit" in text


def run(command, repo, quiet=False):
    """Run a command inside the repo folder and return its text output.

    Raises LitterboxError if the command fails.
    """
    if not quiet:
        diagnostics.LOG("> " + " ".join(command))
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # Stops a black console window flashing up on Windows
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise LitterboxError("Could not run 'git'. Is Git installed?")
    elapsed = time.monotonic() - started
    if diagnostics.DEBUG:
        diagnostics.note_time(command, elapsed)
    if diagnostics.DEBUG and elapsed >= diagnostics.SLOW_SECONDS:                         # in debug mode, slow commands are logged even if quiet
        diagnostics.LOG(f"(slow: {elapsed:.1f}s) " + " ".join(command))
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        if command[:2] == ["git", "commit"] and _nothing_to_commit(result.stdout + "\n" + result.stderr):
            raise NothingToSaveError("Nothing was different from what is already saved in the vault, so there was "
                                     "nothing to save.")
        raise LitterboxError(f"Command failed: {' '.join(command)}\n\n{details}")
    return result.stdout.strip()


CHUNK = 100             # paths per command, so a long list can't pass the Windows command-line limit


def run_chunked(command, paths, repo, quiet=False):
    """Run `command + ['--'] + paths` in pieces. Returns the pieces' output joined together."""
    paths, out = list(paths), []
    for start in range(0, len(paths), CHUNK):
        out.append(run(command + ["--"] + paths[start:start + CHUNK], repo, quiet=quiet))
    return "\n".join(piece for piece in out if piece)
