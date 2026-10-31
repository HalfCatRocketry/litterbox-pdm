"""
remote.py - getting the latest from the vault's remote, and pushing to it.

A pull tells util/file_snapshot first, because git's autostash changes file times. In a vault that downloads on
demand, a pull leaves every changed CAD file as a pointer, so the files that were on disk before the pull are
downloaded again: what you had stays downloaded, and nothing else is. A pull that can't finish (someone
else changed the same file) is undone, so your copy is never left half-way.

A sync (sync) fetches, then brings in what is new without touching your own changed files: if nothing is new, nothing
is done; otherwise a fast-forward, which only rewrites the files the new commits changed. Only when you have commits of
your own not yet uploaded (a push failed), or a new commit changes a file you have changed too, does it fall back to
`git rebase --autostash`, which sets every changed file aside and back. That rewrites them, and Windows won't let git
rewrite a file another program (SolidWorks) has open. Between the fetch and the rest, files of a checkout an Admin
broke are put back (set_aside_broken_checkouts), so they can't stop the sync. The fetch is the only time the vault's
server is asked anything.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.git import repository
from litterbox.git import runner
from litterbox.util import file_snapshot


class UnreachableError(LitterboxError):
    """The vault's server could not be reached (the fetch failed): offline, or the server is down."""


RECOVERED = []          # (folder, [files]) saved by set_aside_broken_checkouts, for the window to tell you about


def take_recovered():
    """What syncing has saved aside since the last call (and forget it): [(folder, [repo-relative files])]."""
    found = list(RECOVERED)
    del RECOVERED[:len(found)]
    return found


def recovered_folder(repo):
    """Where your own copies go when a checkout of yours was broken: beside the vault, never inside it
    (C:\\Litterbox\\hcr-litterbox-recovered\\2026-10-18_153000)."""
    repo = Path(repo).resolve()
    return repo.parent / f"{repo.name}-recovered" / datetime.now().strftime("%Y-%m-%d_%H%M%S")


def set_aside_broken_checkouts(repo):
    """Before a sync: a record or CAD file you have changed but no longer hold the lock on (an Admin broke your
    checkout), which somebody has since changed in the vault, would stop the sync (or be hidden in a git stash).
    So it is put back as it was: a record (it only held your "checked out" entry) is just restored, and a CAD file is
    first copied to the recovered folder, so nothing you did is lost. Called between the fetch and the rebase, so it
    asks the server nothing unless such a file exists (then it reads the lock list). Never raises: if anything can't
    be told, the sync goes ahead as it always did."""
    try:
        incoming = runner.run(["git", "diff", "--name-only", "HEAD...@{upstream}"], repo, quiet=True).splitlines()   # theirs only
        if not incoming:
            return []
        modified = repository.get_modified(repo)
        clash = [path for path in incoming if path.lower() in modified
                 and path.split("/", 1)[0] in (layout.LOG_DIR_NAME, layout.CAD_DIR_NAME,
                                               layout.DOC_LOG_DIR_NAME, layout.DOC_DIR_NAME)]
        if not clash:
            return []
        locks = lfs_locks.get_locks(repo, strict=True)
    except LitterboxError:
        return []
    stale = [path for path in clash if not lfs_locks.is_mine(locks, path)]
    if not stale:
        return []
    saved = [path for path in stale if not path.startswith((layout.LOG_DIR_NAME + "/", layout.DOC_LOG_DIR_NAME + "/"))
             and (Path(repo) / path).is_file()]
    folder = recovered_folder(repo) if saved else None
    try:
        for path in saved:
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(repo) / path, folder / path)
        tracked = repository.in_head_many(repo, stale)
        if tracked:
            runner.run(["git", "restore", "--staged", "--worktree", "--"] + sorted(tracked), repo, quiet=True)
        for path in stale:
            if path not in tracked:
                read_only.delete_file(Path(repo) / path)    # new here, and also new in the vault: the copy is kept
    except (OSError, LitterboxError) as e:
        diagnostics.LOG(f"WARNING: could not put back the files of a broken checkout ({e}); syncing anyway.")
        return []
    diagnostics.LOG("WARNING: you no longer have these checked out (an Admin broke the checkout), and others have "
                    "changed them, so your copies were put back: " + ", ".join(stale)
                    + (f". Your versions of the CAD files are saved in {folder}" if saved else ""))
    if saved:
        RECOVERED.append((folder, saved))
    return stale


def sync(repo):
    """Get the newest commits: fetch, put back the files of a broken checkout, then bring in what is new (see the top
    of this file). Raises UnreachableError if the server can't be reached, and LitterboxError if what is new can't be
    brought in (a rebase is undone first)."""
    try:
        runner.run(["git", "fetch"], repo)
    except LitterboxError as e:
        raise UnreachableError(str(e)) from e
    set_aside_broken_checkouts(repo)
    ahead, behind = (int(n) for n in runner.run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"], repo, quiet=True).split())
    if not behind:
        return                                  # nothing new: your files are left alone
    try:
        if not ahead and not _changes_clash(repo):
            runner.run(["git", "merge", "--ff-only", "@{upstream}"], repo)
            return
        try:
            runner.run(["git", "rebase", "--autostash"], repo)
        except LitterboxError:
            _abort_rebase(repo)                 # never leave your copy half-way through a sync
            raise
    except LitterboxError as e:
        raise _explain_open_files(e) from e


def _changes_clash(repo):
    """Whether a new commit changes a file you have changed (or added) too, which a fast-forward refuses."""
    incoming = runner.run(["git", "diff", "--name-only", "HEAD..@{upstream}"], repo, quiet=True).splitlines()
    modified = repository.get_modified(repo) if incoming else set()
    return any(path.lower() in modified for path in incoming)


def _explain_open_files(error):
    """A sync that couldn't replace a file (git's "unable to unlink old '<file>'") met a file another program, usually
    SolidWorks, has open. Say so; any other error is returned as it is."""
    files = list(dict.fromkeys(re.findall(r"unable to unlink old '([^']+)'", str(error))))
    if not files:
        return error
    names = "\n".join(f"  {name}" for name in files)
    return LitterboxError(f"Could not update these files, because another program (usually SolidWorks) has them "
                          f"open:\n{names}\n\nClose them and try again.\n\n{error}")


def pull(repo):
    on_disk = lfs_download.downloaded_cad_files(repo)
    file_snapshot.before_pull(repo)
    try:
        sync(repo)
        try:
            lfs_download.download(repo, on_disk, "updated files you already had")
        except LitterboxError as e:             # the pull itself worked: say so, and carry on
            diagnostics.LOG(f"WARNING: some files you had could not be downloaded again; they show as not "
                            f"downloaded. {e}")
    finally:
        file_snapshot.after_pull(repo)



def _abort_rebase(repo):
    """If a pull stopped part-way (someone else changed the same file), put your copy back as it was."""
    try:
        states = [runner.run(["git", "rev-parse", "--git-path", name], repo, quiet=True).strip()
                  for name in ("rebase-merge", "rebase-apply")]
        if not any((Path(repo) / state).exists() for state in states):
            return
    except LitterboxError as e:
        diagnostics.LOG(f"WARNING: could not undo an unfinished sync: {e}")
        return
    try:
        runner.run(["git", "rebase", "--abort"], repo, quiet=True)
    except LitterboxError as e:
        # A rebase that failed before it began (its autostash couldn't clear a file) leaves a folder --abort can't
        # read. --quit removes it, leaves your files as they are, and saves the autostash to the stash list.
        try:
            runner.run(["git", "rebase", "--quit"], repo, quiet=True)
            diagnostics.LOG("WARNING: an unfinished sync was cleared. A copy of your changed files was kept in git's "
                            "stash list (git stash list), in case any of them were put back.")
        except LitterboxError as quit_error:
            diagnostics.LOG(f"WARNING: could not undo an unfinished sync: {e}\n{quit_error}")


def commits_behind(repo):
    """How many changes the vault's server has that this copy hasn't got yet (Get Latest would bring them), after a
    quick fetch that changes no files. None if that can't be told: offline, or no server to compare with."""
    try:
        runner.run(["git", "fetch", "--quiet"], repo, quiet=True)
        return int(runner.run(["git", "rev-list", "--count", "HEAD..@{upstream}"], repo, quiet=True).strip() or 0)
    except (LitterboxError, ValueError):
        return None


def latest_text(repo, rel):
    """A vault file's text as the vault's server has it now, after a quick fetch that changes no files (as the server
    last had it if it can't be reached); "" if it has no such file or there is no server to ask."""
    try:
        runner.run(["git", "fetch", "--quiet"], repo, quiet=True)
    except LitterboxError:
        pass
    return repository.quiet_output(repo, "show", f"@{{upstream}}:{rel}")


def push_with_retry(repo, attempts=3, after_sync=None):
    """Sync then push. If someone else pushed first, sync again and retry. after_sync() runs after every sync,
    before the push; it raises to stop the upload. (Litterbox pushes through team/guarded_push.push, which first
    checks that the team list still lets you upload, and after each sync that this Litterbox may still work in the
    vault.)"""
    for attempt in range(1, attempts + 1):
        pull(repo)
        if after_sync is not None:
            after_sync()
        try:
            runner.run(["git", "push"], repo)
            return
        except LitterboxError:
            if attempt == attempts:
                raise
            diagnostics.LOG("Push was rejected. Syncing and trying again...")
