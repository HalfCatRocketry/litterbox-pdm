"""
litterbox_engine.py - the Litterbox "engine". All the git / git-lfs logic lives here.
The GUI imports this file. You can also use it from the command line:

    python litterbox_engine.py <repo_folder> <action> [PN] [-m "text"]

    status                      list every part and who has it
    latest                      get the latest changes from the vault
    checkout  PN                lock a part so you can edit it
    checkin   PN -m "comment"   upload your changes and release the lock
                                (add --anyway to check in even if nothing changed)
    save      PN -m "comment"   upload your changes but KEEP the lock
    undo      PN                throw away your changes and release the lock
    release   PN                freeze the part and its drawing
    reopen    PN -m "reason"    make a released part editable again
    void      PN -m "reason"    abandon a part (its number is never reused)

HOW A PART NUMBER (PN) IS LOCKED
  Everything for one PN is treated as a unit:
      cad/HCR-00042-001.SLDPRT      the part
      cad/HCR-00042-001.SLDDRW      the drawing (if there is one)
      PN-logs/HCR-00042-001.yaml    the record (history, status)
  Checking out a PN locks ALL of them. The lock on the record is the one that
  matters: it is taken first, and it is the only thing that has to succeed for
  someone to be "first". Nobody can edit the record unless they hold that lock.

  Check-out events are written to the record on your computer and uploaded
  together with your files at check-in, so check-out never has to push.

NEEDS in .gitattributes (init_vault.py will write these later; until then, add by hand):
      *.SLDPRT filter=lfs diff=lfs merge=lfs -text lockable    (and .SLDASM, .SLDDRW)
      PN-logs/*.yaml lockable
"""

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path

import yaml

import config
import registry
import pn as pn_module
from pn import PN, PNError
from pn import parse as parse_pn

# Where log messages go. The GUI replaces this with its own function.
LOG = print


class LitterboxError(Exception):
    """Raised when something goes wrong. The message is safe to show to a user."""


class NoChangesError(LitterboxError):
    """A check-in found nothing to upload. Nothing was changed: the part is still checked out.

    `files` lists the CAD files that have no changes. To check in anyway, call
    checkin(..., allow_unchanged=True).
    """

    def __init__(self, pn, files):
        self.pn = pn
        self.files = list(files)
        names = ", ".join(Path(f).name for f in self.files)
        super().__init__(
            f"No changes were detected in {pn}" + (f" ({names})" if names else "") + ".\n"
            "It is still checked out to you. Use Undo Checkout to release it, or check in anyway."
        )


def _converts_errors(func):
    """Make every public function raise only LitterboxError, so callers need one 'except'."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (registry.RegistryError, PNError) as e:
            raise LitterboxError(str(e)) from e
    return wrapper


def _check_permission(repo, user, action):
    """Stop the action unless this user's role allows it.

    Every action that changes something calls this first. `action` is one of:
    create, checkout, checkin, undo, edit_details, release, make_cots, revise,
    cancel_revision, reopen, void (and manage_people / transfer_owner in people.py).
    In a vault with a people file, only active team members pass (see people.py); a vault
    without one lets everybody do everything.
    """
    import people
    people.require(repo, action)


# ---------------------------------------------------------------------------
# Running commands
# ---------------------------------------------------------------------------

SLOW_SECONDS = 2.0
DEBUG = False                  # set from settings.yaml (debug_mode); slow commands are logged only when on


def run(command, repo, quiet=False):
    """Run a command inside the repo folder and return its text output.

    Raises LitterboxError if the command fails.
    """
    if not quiet:
        LOG("> " + " ".join(command))
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
    if DEBUG and elapsed >= SLOW_SECONDS:                         # in debug mode, slow commands are logged even if quiet
        LOG(f"(slow: {elapsed:.1f}s) " + " ".join(command))
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise LitterboxError(f"Command failed: {' '.join(command)}\n\n{details}")
    return result.stdout.strip()


def validate_repo(repo):
    repo = Path(repo)
    if not repo.is_dir():
        raise LitterboxError(f"Repo folder not found:\n{repo}")
    if not (repo / ".git").exists():
        raise LitterboxError(f"This folder is not a git repo (no .git folder):\n{repo}")
    try:
        config.apply(repo)          # learn how this vault writes its part numbers (digit counts)
    except config.ConfigError as e:
        raise LitterboxError(str(e)) from e


def get_user(repo):
    """Your name, for the history. In a vault with a team list it is your name on that list (as last
    verified with the host); otherwise it is the name git has for you."""
    try:
        import people
        identity = people.current(repo, probe=False)
        if identity.state == people.OK:
            return identity.name
    except LitterboxError:
        pass
    try:
        name = run(["git", "config", "user.name"], repo, quiet=True)
    except LitterboxError:
        name = ""
    if not name:
        raise LitterboxError(
            "Git doesn't know your name yet. Run this once, then try again:\n"
            '  git config --global user.name "Your Name"'
        )
    return name


def record_relpath(pn):
    """Where a PN's record lives, relative to the repo, with forward slashes."""
    return f"{registry.LOG_DIR_NAME}/{pn}.yaml"


def _as_pn(value):
    return value if isinstance(value, PN) else parse_pn(value)


# ---------------------------------------------------------------------------
# Reading locks, changes and file state
# ---------------------------------------------------------------------------

def is_pointer(path):
    """True if the file is a tiny LFS pointer, meaning the real file wasn't downloaded."""
    try:
        if path.stat().st_size > 300:
            return False
        with open(path, "rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def get_locks(repo, strict=False):
    """Return {lowercase_path: ("you" or "other", owner_name)} for every lock.

    strict=False: if the lock list can't be read (offline?), warn and return {}.
                  Fine for just displaying things.
    strict=True:  raise LitterboxError instead. Anything that unlocks or changes
                  files uses this, so a network problem can never be mistaken
                  for "nothing is locked".
    """
    try:
        out = run(["git", "lfs", "locks", "--verify", "--json"], repo, quiet=True)
        data = json.loads(out) if out else {}
    except (LitterboxError, json.JSONDecodeError) as e:
        if strict:
            raise LitterboxError(f"Could not read the lock list. Are you online?\n\n{e}")
        LOG(f"WARNING: could not read locks (offline?). {e}")
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


def _is_mine(locks, path):
    return locks.get(path.lower(), ("", ""))[0] == "you"


def get_modified(repo):
    """Return the set of lowercase paths with uncommitted changes (including brand-new files)."""
    out = run(["git", "status", "--porcelain", "--untracked-files=all"], repo, quiet=True)
    modified = set()
    for line in out.splitlines():
        _flag, _, path = line.strip().partition(" ")
        modified.add(path.strip().strip('"').lower())
    return modified


def _head(repo):
    return run(["git", "rev-parse", "HEAD"], repo, quiet=True)


def _changed_between(repo, before, after):
    """Paths that differ between two commits."""
    if before == after:
        return []
    out = run(["git", "diff", "--name-only", before, after], repo, quiet=True)
    return [line for line in out.splitlines() if line]


def _count(repo, rev_range, paths):
    """How many commits in rev_range touch these paths? None if git can't tell
    (for example, no upstream branch is set)."""
    try:
        return int(run(["git", "rev-list", "--count", rev_range, "--"] + list(paths), repo, quiet=True))
    except (LitterboxError, ValueError):
        return None


def _set_read_only(path):
    if path.is_file():
        os.chmod(path, stat.S_IREAD)


def enforce_read_only(repo):
    """Make every managed file read-only unless you hold its lock.

    This is the safety net that stops SolidWorks from saving over a file you
    haven't checked out. It runs after every pull, check-in, undo and so on.
    If the lock list can't be read, it does nothing: guessing wrong here would
    lock you out of files you are editing.
    """
    try:
        locks = get_locks(repo, strict=True)
    except LitterboxError:
        LOG("WARNING: skipped the read-only check because locks could not be read.")
        return
    index = registry.cad_index(repo)
    for pn in registry.list_pns(repo):
        every_file = [f for files in index.get(pn, {}).values() for f in files]
        for rel in every_file + [record_relpath(pn)]:
            if not _is_mine(locks, rel):
                _set_read_only(Path(repo) / rel)


# ---------------------------------------------------------------------------
# Status of every part
# ---------------------------------------------------------------------------

@dataclass
class PartStatus:
    pn: PN
    name: str
    record_status: str          # in_work / released / void
    state: str                  # text to show the user
    kind: str                   # ok, mine, theirs, unclaimed, stray, missing, released, void, error
    locked_by: str = ""
    files: list = field(default_factory=list)   # CAD files, relative to the repo
    description: str = ""
    cots: bool = False
    import_path: str = ""
    revision: str = "A"                 # the working (latest) revision; `files` are this revision's files
    released_revision: str = ""         # the latest released revision, if any
    revisions: dict = field(default_factory=dict)   # {revision: [files]} for every revision that has files
    refs_outdated: bool = False         # an assembly whose list of parts used is missing or out of date
    pending: dict = field(default_factory=dict)     # a release request waiting for sign-offs (see workflow.py)


def get_status(repo):
    """One PartStatus per part number that has a record."""
    validate_repo(repo)
    index = registry.cad_index(repo)
    with ThreadPoolExecutor(max_workers=2) as pool:      # two independent git calls: do them at the same time
        locks_job = pool.submit(get_locks, repo)
        modified_job = pool.submit(get_modified, repo)
        locks, modified = locks_job.result(), modified_job.result()

    rows = []
    for pn in registry.list_pns(repo):
        revisions = index.get(pn, {})
        try:
            record = registry.load(repo, pn)
        except registry.RegistryError as e:
            rows.append(PartStatus(pn, "", "", f"Unreadable record: {e}", "error",
                                   files=sorted(f for fs in revisions.values() for f in fs), revisions=revisions))
            continue
        files = revisions.get(record.revision, [])
        every_file = [f for fs in revisions.values() for f in fs]

        # The record lock is the one that counts; fall back to any file lock.
        lock = locks.get(record_relpath(pn).lower())
        if lock is None:
            lock = next((locks[f.lower()] for f in files if f.lower() in locks), None)
        changed = any(f.lower() in modified for f in every_file)
        not_downloaded = any(is_pointer(Path(repo) / f) for f in files)
        owner = lock[1] if lock else ""

        if record.status == registry.STATUS_VOID:
            state, kind = "Void", "void"
        elif not_downloaded:
            state, kind = "Not downloaded", "missing"
        elif record.pending:
            import workflow
            state, kind = workflow.describe_pending(record.pending), "pending"
        elif record.status == registry.STATUS_RELEASED:
            if changed:
                state, kind = "Released, but its files were modified", "stray"
            else:
                state, kind = "Released", "released"
        elif lock and lock[0] == "you":
            state, kind = "Checked out by you" + (" (modified)" if changed else ""), "mine"
        elif lock:
            state, kind = f"Checked out by {owner}", "theirs"
        elif changed:
            state, kind = "Modified but not checked out", "unclaimed"
        elif record.cots:
            state, kind = "COTS part", "cots"
        elif not files and every_file:
            others = ", ".join(sorted(revisions, key=pn_module.revision_number))
            state, kind = f"No files for Rev {record.revision} (found Rev {others})", "stray"
        elif not files:
            state, kind = "Created, no CAD files yet", "ok"
        else:
            state, kind = "Available", "ok"

        if record.released_revision and record.status != registry.STATUS_RELEASED:
            state += f" (Rev {record.released_revision} released)"
        outdated = any(registry.references_need_update(record, rev, fs) for rev, fs in revisions.items())
        if outdated and kind not in ("error", "missing"):
            state += " (references need updating)"

        rows.append(PartStatus(pn, record.name, record.status, state, kind, owner, files,
                               record.description, record.cots, record.import_path,
                               record.revision, record.released_revision, revisions, outdated, record.pending))
    return rows


# ---------------------------------------------------------------------------
# Building blocks used by the actions
# ---------------------------------------------------------------------------

def _lock(repo, path, label):
    """Lock one file. `label` is the PN, used in the error message."""
    try:
        run(["git", "lfs", "lock", path], repo)
    except LitterboxError:
        lock = get_locks(repo).get(path.lower())
        if lock and lock[0] == "you":
            return                      # already ours, nothing to do
        if lock:
            raise LitterboxError(f"{label} is already checked out by {lock[1]}.")
        raise


def _unlock_mine(repo, paths):
    """Unlock every one of these paths that you hold. Returns [(path, error), ...] for failures."""
    locks = get_locks(repo, strict=True)
    failed = []
    for path in paths:
        if _is_mine(locks, path):
            try:
                run(["git", "lfs", "unlock", path], repo)
            except LitterboxError as e:
                failed.append((path, str(e)))
    return failed


def _force_unlock_quietly(repo, paths):
    """Used when rolling back after an error: release locks, never raise."""
    for path in paths:
        try:
            run(["git", "lfs", "unlock", "--force", path], repo)
        except LitterboxError as e:
            LOG(f"WARNING: could not release the lock on {path}: {e}")


def _discard_quietly(repo, paths):
    """Throw away uncommitted changes to tracked files, never raise."""
    try:
        run(["git", "restore", "--"] + list(paths), repo)
    except LitterboxError as e:
        LOG(f"WARNING: could not restore {', '.join(paths)}: {e}")


def _pull(repo):
    run(["git", "pull", "--rebase", "--autostash"], repo)


def _push_with_retry(repo, attempts=3):
    """Sync then push. If someone else pushed first, sync again and retry.
    First checks that the vault's latest team list still lets you upload."""
    import people
    people.check_before_push(repo)
    for attempt in range(1, attempts + 1):
        _pull(repo)
        try:
            run(["git", "push"], repo)
            return
        except LitterboxError:
            if attempt == attempts:
                raise
            LOG("Push was rejected. Syncing and trying again...")


def _unlock_failure_message(failed):
    lines = "\n".join(f"  {path}: {err.splitlines()[-1] if err else ''}" for path, err in failed)
    return ("Your changes are saved in the vault, but some files could not be unlocked:\n"
            f"{lines}\n\nClick Check In again to retry the unlock "
            "(if it says no changes were detected, choose Continue).")


# ---------------------------------------------------------------------------
# Get latest
# ---------------------------------------------------------------------------

@_converts_errors
def get_latest(repo):
    """Download the newest changes. Returns the list of files that changed.

    If any of those files are open in SolidWorks, they need to be closed and reopened.
    """
    validate_repo(repo)
    before = _head(repo)
    _pull(repo)
    enforce_read_only(repo)
    return _changed_between(repo, before, _head(repo))


# ---------------------------------------------------------------------------
# Check out
# ---------------------------------------------------------------------------

@dataclass
class CheckoutResult:
    files: list                 # the CAD files now checked out to you
    changed_upstream: list      # files that were updated by the download during check-out


@_converts_errors
def checkout(repo, pn):
    """Lock a part (record first, then every CAD file), get the latest copy, log the check-out.

    If anything fails, every lock taken so far is released again.
    """
    validate_repo(repo)
    pn = _as_pn(pn)
    user = get_user(repo)
    _check_permission(repo, user, "checkout")

    record_path = record_relpath(pn)
    if not (Path(repo) / record_path).is_file():
        raise LitterboxError(f"There is no record for {pn} in your copy of the vault. Try Get Latest first.")

    locked = []
    try:
        _lock(repo, record_path, pn)          # whoever gets this lock gets the part
        locked.append(record_path)

        before = _head(repo)
        _pull(repo)                           # lock first, THEN pull: never edit a stale copy
        record = registry.load(repo, pn)      # reload: it may have changed in the pull

        files = registry.cad_files(repo, pn, record.revision)  # after the pull, so new files from others are included
        for f in files:
            _lock(repo, f, pn)
            locked.append(f)

        registry.record_checkout(record, user, files)   # refuses released / void parts
        registry.save(repo, record)
        changed = [p for p in _changed_between(repo, before, _head(repo)) if p in files]
    except BaseException:
        _discard_quietly(repo, [record_path])
        _force_unlock_quietly(repo, locked)
        raise

    enforce_read_only(repo)
    return CheckoutResult(files, changed)


# ---------------------------------------------------------------------------
# Check in / save progress
# ---------------------------------------------------------------------------

@dataclass
class CheckinResult:
    uploaded: bool              # False if there was nothing to upload
    files: list                 # the CAD files whose changes were committed this time


def _record_edited_by_hand(repo, pn, user):
    """True if the PN record has changes beyond the 'checked out' entry Litterbox adds at check-out.

    Without this, fixing a typo in a record looks like "nothing changed" (only CAD
    files were compared), and the check-in would be treated as an undo and throw
    the fix away. A record that has been broken by a hand edit raises an error
    instead of returning False, so a broken edit is never silently discarded.
    """
    record_path = record_relpath(pn)
    try:
        head_text = run(["git", "show", f"HEAD:{record_path}"], repo, quiet=True)
    except LitterboxError:
        return True                                   # not committed yet, so it is new
    try:
        committed = registry.Record.from_dict(yaml.safe_load(head_text))
    except yaml.YAMLError:
        return True

    current = registry.load(repo, pn)                 # raises a clear error if the file is broken
    history = list(current.history)
    if history and history[-1].get("event") == registry.EVENT_CHECKED_OUT and history[-1].get("by") == user:
        history = history[:-1]                        # the entry added by checkout() is expected
    current.history = history
    return current.to_dict() != committed.to_dict()


@dataclass
class ChangeReport:
    has_changes: bool           # anything at all to check in?
    changed_files: list         # CAD files with changes
    unchanged_files: list       # CAD files with no changes
    record_edited: bool         # the PN record was edited by hand
    unpushed: bool              # commits from an earlier failed attempt still need uploading


def _change_report(repo, pn, user):
    record_path = record_relpath(pn)
    cad = registry.cad_files(repo, pn)
    modified = get_modified(repo)
    changed = [f for f in cad if f.lower() in modified]
    record_edited = _record_edited_by_hand(repo, pn, user)
    unpushed = (_count(repo, "@{u}..HEAD", cad + [record_path]) or 0) > 0
    return ChangeReport(
        has_changes=bool(changed or record_edited or unpushed),
        changed_files=changed,
        unchanged_files=[f for f in cad if f not in changed],
        record_edited=record_edited,
        unpushed=unpushed,
    )


@_converts_errors
def change_report(repo, pn):
    """What a check-in of this part would find. Changes nothing. The GUI uses it to
    warn before checking in a part that has no changes."""
    validate_repo(repo)
    pn = _as_pn(pn)
    return _change_report(repo, pn, get_user(repo))


@_converts_errors
def checkin(repo, pn, comment="", keep_lock=False, allow_unchanged=False, references_reader=None):
    """Commit your changes, upload them, then (unless keep_lock) release the locks.

    Order matters: commit, then push, and only then unlock. If any step fails
    you keep your locks and can simply try again.
    keep_lock=True is "Save Progress".

    If nothing has changed, Check In raises NoChangesError and leaves everything
    as it was (it never turns into an undo). With allow_unchanged=True it goes
    ahead anyway: the check-in is recorded in the PN record, uploaded, and the
    locks are released. Save Progress with nothing changed just does nothing.

    references_reader(repo, pn, revision, changed_files) may return the list of parts an assembly
    uses (see references.py), which is stored in the record in the same commit. It returns None
    when there is nothing to update, and any error it raises only costs the update, not the check-in.
    """
    validate_repo(repo)
    pn = _as_pn(pn)
    user = get_user(repo)
    _check_permission(repo, user, "checkin")

    record_path = record_relpath(pn)
    cad = registry.cad_files(repo, pn)
    group = cad + [record_path]

    locks = get_locks(repo, strict=True)
    if not any(_is_mine(locks, p) for p in group):
        raise LitterboxError(f"You don't have {pn} checked out.")

    report = _change_report(repo, pn, user)
    changed = report.changed_files

    if not report.has_changes and not allow_unchanged:
        if keep_lock:
            LOG("No changes to save.")
            return CheckinResult(False, [])
        raise NoChangesError(pn, report.unchanged_files)

    # Commit unless the ONLY thing to do is upload commits left over from an earlier failed attempt.
    if changed or report.record_edited or not report.unpushed:
        record = registry.load(repo, pn)
        found_references = None
        if references_reader is not None:
            try:
                found_references = references_reader(repo, pn, record.revision, changed)
            except Exception as e:
                LOG(f"WARNING: could not read what {pn} uses: {e}")
        registry.record_checkin(record, user, changed, comment, references=found_references)
        registry.save(repo, record)
        message = f"{pn}: {(comment or '').strip() or 'Update'}"
        run(["git", "add", "--"] + changed + [record_path], repo)
        run(["git", "commit", "-m", message, "--"] + changed + [record_path], repo)

    _push_with_retry(repo)

    if keep_lock:
        # Brand-new files weren't lockable before they were uploaded. Lock them now.
        locks = get_locks(repo, strict=True)
        for f in cad:
            if f.lower() not in locks:
                _lock(repo, f, pn)
    else:
        failed = _unlock_mine(repo, group)
        enforce_read_only(repo)
        if failed:
            raise LitterboxError(_unlock_failure_message(failed))
    return CheckinResult(True, changed)


@_converts_errors
def edit_details(repo, pn, name, description):
    """Change a part's name and description. You must have the part checked out.

    The change is made in your copy of the record only. It is uploaded with your next
    Save Progress or Check In (and thrown away by Undo Checkout). Returns True if
    anything changed.
    """
    validate_repo(repo)
    pn = _as_pn(pn)
    user = get_user(repo)
    _check_permission(repo, user, "edit_details")
    if not _is_mine(get_locks(repo, strict=True), record_relpath(pn)):
        raise LitterboxError(f"You don't have {pn} checked out. Check it out to change its name or description.")
    record = registry.load(repo, pn)
    changed = registry.edit_details(record, user, name, description) is not None
    if changed:
        registry.save(repo, record)
    return changed


# ---------------------------------------------------------------------------
# Undo check out
# ---------------------------------------------------------------------------

@_converts_errors
def undo_checkout(repo, pn):
    """Throw away your changes to a part and release its locks.

    The check-out event is discarded along with the changes. Brand-new files you
    created that were never uploaded are NOT deleted. Their names are returned.
    """
    validate_repo(repo)
    pn = _as_pn(pn)
    user = get_user(repo)
    _check_permission(repo, user, "undo")

    record_path = record_relpath(pn)
    group = registry.cad_files(repo, pn) + [record_path]

    locks = get_locks(repo, strict=True)
    if not any(_is_mine(locks, p) for p in group):
        raise LitterboxError(f"You don't have {pn} checked out.")

    if (_count(repo, "@{u}..HEAD", group) or 0) > 0:
        raise LitterboxError(
            f"Some changes to {pn} were already saved on your computer but not uploaded yet.\n"
            "Use Check In to upload them. Undo would leave them stranded."
        )

    tracked = {t.lower() for t in run(["git", "ls-files", "--"] + group, repo, quiet=True).splitlines()}
    to_restore = [p for p in group if p.lower() in tracked]
    never_uploaded = [p for p in group if p.lower() not in tracked]
    if to_restore:
        run(["git", "restore", "--"] + to_restore, repo)

    failed = _unlock_mine(repo, group)
    enforce_read_only(repo)
    if failed:
        raise LitterboxError(_unlock_failure_message(failed))
    return never_uploaded


# ---------------------------------------------------------------------------
# Release, reopen, void (all edit the record under a short lock)
# ---------------------------------------------------------------------------

@dataclass
class ReleasePlan:
    pn: PN
    name: str
    files: list                 # the CAD files that would be frozen
    problems: list = field(default_factory=list)   # reasons it can't go ahead
    warnings: list = field(default_factory=list)   # things to be aware of; the release can still go ahead

    @property
    def ok(self):
        return not self.problems


def _blockers(repo, pn, record, verb, fetch, required=registry.STATUS_IN_WORK, required_label="in-work",
              allow_pending=False):
    """Shared by release, Make COTS and Revise: the working revision's CAD files, and the reasons
    the part can't go ahead yet (checked out, modified, behind the vault...)."""
    record_path = record_relpath(pn)
    cad = registry.cad_files(repo, pn, record.revision)
    group = cad + [record_path]
    problems = []

    if record.status != required:
        problems.append(f"Its status is '{record.status}'. Only {required_label} parts can be {verb}.")
    if record.pending and not allow_pending:
        problems.append("It is waiting for sign-offs on a release request.")
    if not cad:
        problems.append("There are no CAD files for it in the cad folder.")

    if fetch:   # look at the vault's current state without changing any of your files
        try:
            run(["git", "fetch"], repo, quiet=True)
        except LitterboxError as e:
            LOG(f"WARNING: could not check the vault for newer changes. {e}")

    locks = get_locks(repo, strict=True)
    owners = sorted({locks[p.lower()][1] for p in group if p.lower() in locks})
    if owners:
        problems.append("It is checked out by " + ", ".join(owners) + ".")

    modified = get_modified(repo)
    for f in cad:
        if f.lower() in modified:
            problems.append(f"{f} has changes that are not checked in.")
        elif is_pointer(Path(repo) / f):
            problems.append(f"{f} has not been downloaded. Run Get Latest.")

    if (_count(repo, "@{u}..HEAD", group) or 0) > 0:
        problems.append("Some changes have not been uploaded yet.")
    if (_count(repo, "HEAD..@{u}", group) or 0) > 0:
        problems.append("A newer version is in the vault. Run Get Latest first.")
    return cad, problems


@_converts_errors
def release_plan(repo, pn, fetch=True, allow_pending=False):
    """Work out what a release would freeze and whether anything blocks it.

    Show plan.files to the user for confirmation, and plan.problems if it isn't ok.
    """
    validate_repo(repo)
    pn = _as_pn(pn)
    record = registry.load(repo, pn)
    cad, problems = _blockers(repo, pn, record, "released", fetch, allow_pending=allow_pending)
    if record.cots:
        problems.insert(0, "It is a COTS (purchased) part, which is never released.")
    warnings = []
    rule = config.get_release_rule(repo)
    if rule != "off" and not record.cots:
        import references
        found = references.release_warnings(repo, pn)
        if rule == "block":
            problems.extend(found)
        else:
            warnings = found
    return ReleasePlan(pn, record.name, cad, problems, warnings)


@_converts_errors
def make_cots_plan(repo, pn, fetch=True):
    """Work out whether a part can be turned into a COTS part. Same checks as a release:
    nobody has it checked out, nothing is modified, and your copy is up to date."""
    validate_repo(repo)
    pn = _as_pn(pn)
    record = registry.load(repo, pn)
    cad, problems = _blockers(repo, pn, record, "made COTS", fetch)
    if record.cots:
        problems.insert(0, "It is already a COTS part.")
    elif record.released_revision or record.revision != pn_module.FIRST_REVISION:
        problems.insert(0, "It has been released or revised, so it is not an unmodified purchased part.")
    return ReleasePlan(pn, record.name, cad, problems)


def _edit_record(repo, pn, action, edit, message):
    """Lock a record, apply `edit(record, user)`, commit, push, unlock.

    If anything goes wrong the record is put back the way it was and the lock
    is released.
    """
    validate_repo(repo)
    user = get_user(repo)
    _check_permission(repo, user, action)

    record_path = record_relpath(pn)
    if not (Path(repo) / record_path).is_file():
        raise LitterboxError(f"There is no record for {pn} in your copy of the vault. Try Get Latest first.")

    _lock(repo, record_path, pn)
    committed = False
    try:
        _pull(repo)
        record = registry.load(repo, pn)       # reload after the pull
        edit(record, user)                     # raises if the change isn't allowed
        registry.save(repo, record)
        run(["git", "add", "--", record_path], repo)
        run(["git", "commit", "-m", message, "--", record_path], repo)
        committed = True
        _push_with_retry(repo)
    except BaseException:
        try:
            if committed:
                run(["git", "reset", "--soft", "HEAD~1"], repo)       # take back our unpushed commit
            run(["git", "restore", "--staged", "--worktree", "--", record_path], repo)
        except LitterboxError as e:
            LOG(f"WARNING: could not fully undo the change to {record_path}: {e}")
        _force_unlock_quietly(repo, [record_path])
        raise

    failed = _unlock_mine(repo, [record_path])
    enforce_read_only(repo)
    if failed:
        raise LitterboxError(_unlock_failure_message(failed))


def _one_line(text):
    return " ".join((text or "").split())


@_converts_errors
def release(repo, pn):
    """Freeze a part and its drawing. Call release_plan() first and get the user to confirm.

    Returns the list of files that were released.
    """
    pn = _as_pn(pn)
    import workflow
    if workflow.template_for(repo, "release") is not None:
        raise LitterboxError("Releases in this vault need sign-offs. Use Release to ask for them; the part is "
                             "released when everyone required has signed.")
    plan = release_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be released yet:\n- " + "\n- ".join(plan.problems))
    _edit_record(
        repo, pn, "release",
        lambda record, user: registry.mark_released(record, user, plan.files),
        f"{pn}: Released",
    )
    return plan.files


@_converts_errors
def make_cots(repo, pn):
    """Record an existing part as COTS (purchased): it can no longer be checked out.
    Call make_cots_plan() first and get the user to confirm. Returns the files it covers."""
    pn = _as_pn(pn)
    plan = make_cots_plan(repo, pn)
    if not plan.ok:
        raise LitterboxError(f"{pn} can't be made COTS yet:\n- " + "\n- ".join(plan.problems))
    _edit_record(
        repo, pn, "make_cots",
        lambda record, user: registry.mark_cots(record, user, plan.files),
        f"{pn}: Made COTS",
    )
    return plan.files


@_converts_errors
def reopen(repo, pn, reason):
    """Make a released part editable again. A reason is required."""
    pn = _as_pn(pn)
    _edit_record(
        repo, pn, "reopen",
        lambda record, user: registry.mark_reopened(record, user, reason),
        f"{pn}: Reopened - {_one_line(reason)}",
    )


@_converts_errors
def void(repo, pn, reason):
    """Abandon a part. Its number is never reused. A reason is required."""
    pn = _as_pn(pn)
    _edit_record(
        repo, pn, "void",
        lambda record, user: registry.mark_void(record, user, reason),
        f"{pn}: Voided - {_one_line(reason)}",
    )


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

def _print_status(repo):
    rows = get_status(repo)
    if not rows:
        print("No parts yet.")
    for row in rows:
        print(f"{row.pn}  {row.state:<38} {row.name}")


def main():
    parser = argparse.ArgumentParser(description="Litterbox engine")
    parser.add_argument("repo", help="path to the repo folder")
    parser.add_argument("action", choices=["status", "latest", "checkout", "checkin", "save",
                                           "undo", "release", "makecots", "reopen", "void"])
    parser.add_argument("pn", nargs="?", help="part number, for example HCR-00042-001")
    parser.add_argument("-m", "--message", default="", help="comment or reason")
    parser.add_argument("--anyway", action="store_true",
                        help="check in even if no changes were detected")
    args = parser.parse_args()

    try:
        if args.action == "status":
            _print_status(args.repo)
        elif args.action == "latest":
            changed = get_latest(args.repo)
            print(f"{len(changed)} file(s) changed." + ("\n  " + "\n  ".join(changed) if changed else ""))
        else:
            if not args.pn:
                parser.error(f"'{args.action}' needs a part number")
            if args.action in ("reopen", "void") and not args.message.strip():
                parser.error(f"'{args.action}' needs a reason: -m \"why\"")

            if args.action == "checkout":
                result = checkout(args.repo, args.pn)
                if result.changed_upstream:
                    print("Newer versions were downloaded. Close and reopen these in SolidWorks:")
                    print("  " + "\n  ".join(result.changed_upstream))
            elif args.action in ("checkin", "save"):
                result = checkin(args.repo, args.pn, args.message, keep_lock=(args.action == "save"),
                                 allow_unchanged=args.anyway)
                if not result.uploaded:
                    print("There were no changes to upload.")
            elif args.action == "undo":
                left = undo_checkout(args.repo, args.pn)
                if left:
                    print("These new files were never uploaded, so they were left alone:")
                    print("  " + "\n  ".join(left))
            elif args.action == "release":
                plan = release_plan(args.repo, args.pn)
                if not plan.ok:
                    print("Can't release yet:\n- " + "\n- ".join(plan.problems))
                    sys.exit(1)
                print(f"This will release {plan.pn} ({plan.name}) and freeze:")
                print("  " + "\n  ".join(plan.files))
                if input("Release these files? [y/N] ").strip().lower() != "y":
                    print("Cancelled.")
                    return
                release(args.repo, args.pn)
            elif args.action == "makecots":
                plan = make_cots_plan(args.repo, args.pn)
                if not plan.ok:
                    print("Can't make it COTS yet:\n- " + "\n- ".join(plan.problems))
                    sys.exit(1)
                print(f"This will record {plan.pn} ({plan.name}) as a COTS part, which can't be checked out:")
                print("  " + "\n  ".join(plan.files))
                if input("Make it COTS? [y/N] ").strip().lower() != "y":
                    print("Cancelled.")
                    return
                make_cots(args.repo, args.pn)
            elif args.action == "reopen":
                reopen(args.repo, args.pn, args.message)
            elif args.action == "void":
                void(args.repo, args.pn, args.message)
        print("\nDone.")
    except LitterboxError as e:
        print(f"\nERROR: {e}")
        if isinstance(e, NoChangesError):
            print("Add --anyway to check in anyway.")
        sys.exit(1)


if __name__ == "__main__":
    main()
