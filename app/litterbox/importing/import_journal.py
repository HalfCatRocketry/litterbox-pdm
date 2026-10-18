"""
import_journal.py - the note of what an unfinished import has put in the vault, and recover(), which
puts the vault back if an import stopped half way (or finishes it, if its commit was already pushed).
"""

import os
from pathlib import Path

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import committing
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.importing import import_errors
from litterbox.util import journal as journal_file


JOURNAL_NAME = "litterbox-import.json"


JOURNAL_VERSION = 1


def _journal_path(repo):
    return journal_file.path(repo, JOURNAL_NAME)


def write_journal(repo, phase, token, files, records):
    journal_file.write(repo, JOURNAL_NAME, {"version": JOURNAL_VERSION, "phase": phase, "token": token,
                                            "files": files, "records": records})


def read_journal(repo):
    path = _journal_path(repo)
    try:
        data = journal_file.load(repo, JOURNAL_NAME, JOURNAL_VERSION)
        if data is None:
            return None
        files, records = list(data["files"]), list(data["records"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise import_errors.ImportFailed(f"The note about an unfinished import ({path}) can't be read ({e}). "
                           "Delete it by hand if you are sure no import is running, then try again.") from None
    for rel in files:
        if not str(rel).startswith(f"{layout.CAD_DIR_NAME}/") or ".." in str(rel):
            raise import_errors.ImportFailed(f"The note about an unfinished import lists a file outside the cad folder ({rel}). "
                               f"Litterbox will not delete it. Check {_journal_path(repo)} by hand.")
    for rel in records:
        if not str(rel).startswith(f"{layout.LOG_DIR_NAME}/") or ".." in str(rel):
            raise import_errors.ImportFailed(f"The note about an unfinished import lists a record outside PN-logs ({rel}). "
                               f"Litterbox will not delete it. Check {_journal_path(repo)} by hand.")
    return {"phase": data.get("phase", ""), "token": str(data.get("token", "")), "files": files, "records": records}


def clear_journal(repo):
    journal_file.clear(repo, JOURNAL_NAME)


def unpushed(repo):
    try:
        return int(repository.quiet_output(repo, "rev-list", "--count", "@{u}..HEAD") or 0)
    except ValueError:
        return 0


def our_commit(repo, token):
    """The hash of the commit this import made (found by the token in its message), or ''."""
    if not token:
        return ""
    return repository.quiet_output(repo, "log", "-1", "--format=%H", f"--grep={token}", "HEAD")


def recover(repo, log=print):
    """Clean up after an import that was interrupted or abandoned. Returns 'nothing', 'cleaned' or 'finished'.

    It removes exactly the files and records the import's note lists, and only those that the
    vault does not own (nothing that is in the latest commit is ever touched). If the note shows
    the import's commit had in fact reached the vault, the import is kept ('finished').
    """
    repository.validate_repo(repo)
    journal = read_journal(repo)
    if journal is None:
        return "nothing"
    files, records = journal["files"], journal["records"]
    commit = our_commit(repo, journal["token"])
    if commit:
        if unpushed(repo) == 0:
            clear_journal(repo)
            read_only.enforce_read_only(repo)
            log("The unfinished import had actually reached the vault, so it was kept. "
                "Its manifest was not updated.")
            return "finished"
        if repository.quiet_output(repo, "rev-parse", "HEAD") != commit:
            raise import_errors.ImportFailed("An unfinished import left a commit that has not been pushed, but it is no longer "
                               "the latest commit, so Litterbox will not undo it. Ask for help before continuing.")
        runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
    ours = [rel for rel in files + records if not repository.in_head(repo, rel)]
    log(f"Removing {len(ours)} file(s) left by an unfinished import...")
    if ours:
        pathspec = committing.write_pathspec(ours)
        try:
            runner.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", f"--pathspec-from-file={pathspec}"], repo)
        except LitterboxError as e:
            log(f"WARNING: could not fully clean git's index: {e}")
        finally:
            try:
                os.unlink(pathspec)
            except OSError:
                pass
    problems = []
    for rel in ours:
        path = Path(repo) / rel
        try:
            if path.exists():
                os.chmod(path, 0o644)
                path.unlink()
        except OSError as e:
            problems.append(f"{rel}: {e}")
    if problems:
        raise import_errors.ImportFailed("Some files from an unfinished import could not be deleted (are they open in "
                           "SolidWorks?). Close them and try again:\n" + "\n".join(problems[:8]))
    clear_journal(repo)
    read_only.enforce_read_only(repo)
    return "cleaned"
