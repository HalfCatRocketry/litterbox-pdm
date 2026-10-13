r"""
importer.py - bring the files listed in a manifest into the vault.

    python importer.py <vault> <manifest.yaml> [--dry-run] [--allow-external] [--recover]

What it does
  Every included item that has no part number yet gets a NEW one. Its SolidWorks files are
  copied (never moved, never changed) into the vault's cad folder as HCR-00042-001.SLDPRT and
  so on, and every reference inside the copies is pointed at the other copies, so the imported
  files only know about each other. Your old folders are not written to.

  Nothing is reserved while this runs. The part numbers are only picked from the vault as it
  is now; they become yours when the records and the CAD files are committed and pushed in ONE
  step at the very end. That is why cancelling is clean:

    * Cancel (or an error, or closing the window) deletes exactly the files this import copied,
      and nothing else, and leaves git as it was. The numbers were never taken, so there is
      nothing to give back and the next attempt starts from the same place.
    * If the computer dies in the middle, a note kept inside the vault's .git folder lists the
      files that were copied. The next import (or `--recover`) removes them first.
    * If somebody else uses one of the numbers while you were copying, the copies are removed
      and the import starts again with the newest numbers (up to 3 tries).

  The manifest is only updated (each item's pn) after everything is in the vault.

PART NUMBERS
  prepare() refreshes the vault and PROPOSES a block of numbers well above the highest one in
  use (100 or more above it), so other people creating parts meanwhile are very unlikely to
  reach them. Nothing is reserved or pushed. The proposal is a table (Proposal.entries) the user
  can edit: part number, name, description. finish() then downloads the newest records and
  checks every number again:
    * an automatic number that has been taken is quietly replaced by a free one;
    * a number the user typed that has been taken is never changed: PNConflict is raised before
      anything is copied, listing the rows to highlight, and finish() can simply be called again
      after the table is corrected.

  --dry-run      do all the checking and show what would happen, without writing anything
  --allow-external   go ahead even though some files reference files that are not part of this
                 import (those references are left pointing at the original files)
  --recover      clean up after an interrupted import, then stop
"""

import argparse
import json
import os
import random
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import config
import create
import litterbox_engine as eng
import manifest as manifest_module
import pn as pn_module
import registry
from pn import PN

JOURNAL_NAME = "litterbox-import.json"
JOURNAL_VERSION = 1
ATTEMPTS = 3
MODEL_EXTENSIONS = {".sldprt", ".sldasm"}
DRAWING_EXTENSION = ".slddrw"


class ImportFailed(eng.LitterboxError):
    """The import could not be done. The message is safe to show to a user. Nothing was left behind."""


class FamilyFull(ImportFailed):
    """More parts are being imported to one base number than it has unused variant numbers."""


class ExternalReferences(ImportFailed):
    """Some files reference files that are not part of the import. `references` is [(file, referenced file)].

    The caller may ask the user and, if they agree, try again with allow_external.
    """

    def __init__(self, message, references):
        super().__init__(message)
        self.references = list(references)


class ImportCancelled(ImportFailed):
    """The user cancelled. Everything copied so far has been removed."""


@dataclass
class Plan:
    """What an import will do (built without writing anything)."""
    items: list
    specs: list
    pns: list
    copies: dict            # original path -> new path in cad\
    order: list             # original paths, in the order they must be copied
    repoints: dict          # original path -> [(stored reference, new target path)]
    external: list = field(default_factory=list)      # (original path, reference left pointing outside)
    kept: dict = field(default_factory=dict)          # original path key -> keys of stored references left as they were
    warnings: list = field(default_factory=list)


@dataclass
class Result:
    pns: list = field(default_factory=list)
    files: list = field(default_factory=list)         # relative paths of the CAD files added
    warnings: list = field(default_factory=list)
    plan: Plan = None
    dry_run: bool = False
    version: str = ""
    renumbered: list = field(default_factory=list)    # (row, old PN, new PN) automatic numbers replaced at the end


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _extension(path):
    return os.path.splitext(path)[1].lower()


def is_inside(path, folder):
    folder = _key(folder).rstrip("\\/") + os.sep
    return _key(path).startswith(folder)


def pair_references(stored, found):
    """[(stored path, found path)] for one file's references.

    `stored` is what the file says (it may be an old folder that no longer exists) and `found`
    is where SolidWorks finds each file when it searches. Normally the two lists line up. If they
    don't, they are matched by file name, and a stored reference with no unique match gets ''.
    """
    stored, found = list(stored), list(found)
    if len(stored) == len(found) and all(
            os.path.basename(a).lower() == os.path.basename(b).lower() for a, b in zip(stored, found)):
        return list(zip(stored, found))
    pairs = []
    for ref in stored:
        name = os.path.basename(ref).lower()
        matches = [f for f in found if os.path.basename(f).lower() == name]
        pairs.append((ref, matches[0] if len(matches) == 1 else ""))
    return pairs


def _cad_target(repo, pn, original_path):
    return str(registry.cad_dir(repo) / pn_module.filename(pn, pn_module.FIRST_REVISION, _extension(original_path)))


def _relative(repo, path):
    return Path(os.path.relpath(path, repo)).as_posix()


def _snapshot(paths):
    result = {}
    for path in paths:
        try:
            st = os.stat(path)
            result[path] = (st.st_size, st.st_mtime_ns)
        except OSError:
            result[path] = None
    return result


# ---------------------------------------------------------------------------
# The journal: a note of what an unfinished import has put in the vault
# ---------------------------------------------------------------------------

def _journal_path(repo):
    return Path(repo) / ".git" / JOURNAL_NAME


def _write_journal(repo, phase, token, files, records):
    data = {"version": JOURNAL_VERSION, "phase": phase, "token": token, "files": files, "records": records}
    path = _journal_path(repo)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


def _read_journal(repo):
    path = _journal_path(repo)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != JOURNAL_VERSION:
            raise ValueError("unknown version")
        files, records = list(data["files"]), list(data["records"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ImportFailed(f"The note about an unfinished import ({path}) can't be read ({e}). "
                           "Delete it by hand if you are sure no import is running, then try again.") from None
    for rel in files:
        if not str(rel).startswith(f"{registry.CAD_DIR_NAME}/") or ".." in str(rel):
            raise ImportFailed(f"The note about an unfinished import lists a file outside the cad folder ({rel}). "
                               f"Litterbox will not delete it. Check {_journal_path(repo)} by hand.")
    for rel in records:
        if not str(rel).startswith(f"{registry.LOG_DIR_NAME}/") or ".." in str(rel):
            raise ImportFailed(f"The note about an unfinished import lists a record outside PN-logs ({rel}). "
                               f"Litterbox will not delete it. Check {_journal_path(repo)} by hand.")
    return {"phase": data.get("phase", ""), "token": str(data.get("token", "")), "files": files, "records": records}


def _clear_journal(repo):
    try:
        _journal_path(repo).unlink()
    except FileNotFoundError:
        pass


def _git_out(repo, *args):
    try:
        return eng.run(["git", *args], repo, quiet=True)
    except eng.LitterboxError:
        return ""


def _unpushed(repo):
    try:
        return int(_git_out(repo, "rev-list", "--count", "@{u}..HEAD") or 0)
    except ValueError:
        return 0


def _tracked(repo, rel):
    """True if the latest commit has this file (so it belongs to the vault, not to a half-finished import)."""
    return bool(_git_out(repo, "ls-tree", "HEAD", "--", rel))


def _our_commit(repo, token):
    """The hash of the commit this import made (found by the token in its message), or ''."""
    if not token:
        return ""
    return _git_out(repo, "log", "-1", "--format=%H", f"--grep={token}", "HEAD")


def recover(repo, log=print):
    """Clean up after an import that was interrupted or abandoned. Returns 'nothing', 'cleaned' or 'finished'.

    It removes exactly the files and records the import's note lists, and only those that the
    vault does not own (nothing that is in the latest commit is ever touched). If the note shows
    the import's commit had in fact reached the vault, the import is kept ('finished').
    """
    eng.validate_repo(repo)
    journal = _read_journal(repo)
    if journal is None:
        return "nothing"
    files, records = journal["files"], journal["records"]
    commit = _our_commit(repo, journal["token"])
    if commit:
        if _unpushed(repo) == 0:
            _clear_journal(repo)
            eng.enforce_read_only(repo)
            log("The unfinished import had actually reached the vault, so it was kept. "
                "Its manifest was not updated.")
            return "finished"
        if _git_out(repo, "rev-parse", "HEAD") != commit:
            raise ImportFailed("An unfinished import left a commit that has not been pushed, but it is no longer "
                               "the latest commit, so Litterbox will not undo it. Ask for help before continuing.")
        eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
    ours = [rel for rel in files + records if not _tracked(repo, rel)]
    log(f"Removing {len(ours)} file(s) left by an unfinished import...")
    if ours:
        pathspec = create._write_pathspec(ours)
        try:
            eng.run(["git", "rm", "--cached", "-q", "--ignore-unmatch", f"--pathspec-from-file={pathspec}"], repo)
        except eng.LitterboxError as e:
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
        raise ImportFailed("Some files from an unfinished import could not be deleted (are they open in "
                           "SolidWorks?). Close them and try again:\n" + "\n".join(problems[:8]))
    _clear_journal(repo)
    eng.enforce_read_only(repo)
    return "cleaned"


# ---------------------------------------------------------------------------
# SolidWorks (the only part that needs Windows)
# ---------------------------------------------------------------------------

class SolidWorksBackend:
    """The four things the importer needs from SolidWorks. None of them writes to an original file.

    references(path)         [(stored, found)] for the file's direct references
    copy(src, dst)           copy a file on disk (nothing needs to be open)
    repoint(file, old, new)  change one reference inside the NEW file
    version()                the SolidWorks version, for the log
    """

    def __init__(self, attach_only=False):
        self._sw = None
        self._started_by_us = False
        self._pid = None                    # the process of a SolidWorks we started, learned while it is alive
        self.attach_only = attach_only      # True: use a SolidWorks that is already running, never start one

    def _app(self):
        if self._sw is None:
            import sw_probe
            try:
                if self.attach_only:
                    import win32com.client
                    self._sw, self._started_by_us = win32com.client.GetActiveObject("SldWorks.Application"), False
                else:
                    before = solidworks_pids()
                    self._sw, self._started_by_us = sw_probe.connect()
                    if self._started_by_us:
                        self._pid = own_process_id(self._sw, before)
            except Exception as e:
                if self.attach_only:
                    raise ImportFailed("SolidWorks is not open.") from None
                raise ImportFailed("Litterbox could not connect to SolidWorks. Is it installed on this computer?\n\n"
                                   f"{e}") from None
        return self._sw

    def _dependencies(self, path, search):
        import sw_probe
        deps = sw_probe.call(self._app(), "GetDocumentDependencies2", path, False, search, False) or []
        return [p for p in list(deps)[1::2] if isinstance(p, str)]

    def references(self, path):
        return pair_references(self._dependencies(path, False), self._dependencies(path, True))

    def copy(self, src, dst):
        import pythoncom
        from win32com.client import VARIANT
        os.makedirs(os.path.dirname(dst), exist_ok=True)         # CopyDocument will not create the folder
        empty = lambda: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [])
        result = self._app().CopyDocument(src, dst, empty(), empty(), 0)
        if os.path.exists(dst):
            return
        # SolidWorks refused. A single part that uses no other files (a purchased washer, say) has nothing for
        # SolidWorks to update inside the copy, so an ordinary file copy gives exactly the same result.
        if src.lower().endswith(".sldprt"):
            try:
                alone = not self._dependencies(src, False)
            except Exception:
                alone = False
            if alone:
                shutil.copyfile(src, dst)
                return
        raise ImportFailed(f"SolidWorks could not copy {src} (it returned {result!r}).\n\nIf the file is open in "
                           "SolidWorks, close it and try again. Check that you can open it, and that it is not "
                           "in a folder SolidWorks can't read.")

    def repoint(self, file, old, new):
        return bool(self._app().ReplaceReferencedDocument(file, old, new))

    def version(self):
        app = self._app()                       # a failure to connect should be reported, not hidden
        try:
            return str(app.RevisionNumber)
        except Exception:
            return ""

    def close(self):
        """Shut down the SolidWorks we started (never one that was already running), and make sure it is gone.

        A SolidWorks started by a program runs hidden. If it lingers, Windows later hands "Open" to that
        hidden copy, and the part opens in a window nobody can see. So after ExitApp we let go of our hold
        on it, wait for its process to end, and end it ourselves if it will not."""
        sw, self._sw = self._sw, None
        if sw is None or not self._started_by_us:
            return
        pid = self._pid
        if not pid:
            try:
                pid = int(sw.GetProcessID())
            except Exception:
                pass
        try:
            sw.ExitApp()
        except Exception:
            pass
        del sw
        import gc
        gc.collect()                                      # let go of any COM objects still pointing at it
        if pid:
            wait_for_exit(pid, log=lambda message: eng.LOG(message))
        else:
            eng.LOG("Could not tell which SolidWorks process Litterbox started, so could not check it had exited.")


def solidworks_pids():
    """The process ids of every SLDWORKS.exe running now (empty if none, or on a system without tasklist)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[0].strip('"').lower() == "sldworks.exe" and parts[1].strip('"').isdigit():
            pids.add(int(parts[1].strip('"')))
    return pids


def own_process_id(sw, before):
    """The process id of a SolidWorks we just started: SolidWorks's own answer, or else the one that is new."""
    try:
        return int(sw.GetProcessID())
    except Exception:
        pass
    new = solidworks_pids() - set(before or ())
    return next(iter(new)) if len(new) == 1 else None


def process_is_running(pid):
    """Is this Windows process still running? (False on any other system.)"""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False                                            # no such process any more
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    except Exception:
        return False


def end_process(pid):
    """Force a process to end."""
    import subprocess
    subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


EXIT_WAIT_SECONDS = 5.0       # how long a SolidWorks we started gets to exit by itself before we end it


def wait_for_exit(pid, timeout=EXIT_WAIT_SECONDS, alive=process_is_running, kill=end_process, sleep=None,
                  log=None):
    """Wait for a process to finish by itself; end it if it takes longer than `timeout` seconds.
    Returns "exited" or "ended"."""
    import time
    sleep = sleep or time.sleep
    waited = 0.0
    while alive(pid):
        if waited >= timeout:
            try:
                kill(pid)
            except Exception:
                pass
            if log:
                log(f"SolidWorks (process {pid}) did not exit by itself, so Litterbox ended it.")
            return "ended"
        sleep(0.25)
        waited += 0.25
    return "exited"


# ---------------------------------------------------------------------------
# Planning (reads only)
# ---------------------------------------------------------------------------

def _item_files(item):
    return [f.path for f in item.files]


def read_references(items, backend, progress=None, cancel=None):
    """{key: (path, [(stored, found)])} for every file in the import."""
    paths = [p for item in items for p in _item_files(item)]
    refs = {}
    for number, path in enumerate(paths, start=1):
        _check_cancel(cancel)
        if progress:
            progress(number, len(paths), f"Reading references: {os.path.basename(path)}")
        try:
            refs[_key(path)] = (path, backend.references(path))
        except ImportFailed:
            raise
        except Exception as e:
            raise ImportFailed(f"Could not read the references of {path}:\n{e}") from e
    return refs


def _order(items, refs):
    """The original files in copy order: models before what uses them, then the drawings."""
    in_set = {_key(p): p for item in items for p in _item_files(item)}
    models = [p for p in in_set.values() if _extension(p) in MODEL_EXTENSIONS]
    drawings = [p for p in in_set.values() if _extension(p) == DRAWING_EXTENSION]
    others = [p for p in in_set.values() if p not in models and p not in drawings]
    order, done = [], set()

    def visit(path, trail):
        key = _key(path)
        if key in done:
            return
        if key in trail:
            raise ImportFailed(f"{path} ends up referencing itself, so there is no order to copy these files in.")
        for _stored, found in refs[key][1]:
            if found and _key(found) in in_set and _extension(found) in MODEL_EXTENSIONS:
                visit(in_set[_key(found)], trail | {key})
        done.add(key)
        order.append(path)

    for path in sorted(models, key=lambda p: p.lower()):
        visit(path, frozenset())
    return order + sorted(others, key=lambda p: p.lower()) + sorted(drawings, key=lambda p: p.lower())


def build_plan(repo, items, specs, pns, refs, manifest, allow_external=False):
    """Work out where every file goes and which references to change. Raises ImportFailed for blockers."""
    copies = {}
    for item, pn in zip(items, pns):
        for path in _item_files(item):
            copies[_key(path)] = _cad_target(repo, pn, path)
    new_paths = set(copies.values())
    clash = [p for p in new_paths if os.path.exists(p)]
    if clash:
        raise ImportFailed("These files are already in the vault's cad folder, and Litterbox will not overwrite "
                           "them:\n" + "\n".join(clash[:8]))

    # Files imported earlier (their items already have a pn) are valid targets too.
    known = dict(copies)
    for item in manifest.items:
        if item.pn:
            pn = pn_module.try_parse(item.pn)
            for path in _item_files(item):
                target = _cad_target(repo, pn, path) if pn else None
                if target and os.path.exists(target):
                    known.setdefault(_key(path), target)

    order = _order(items, refs)
    repoints, external, warnings, kept = {}, [], [], {}
    for path in order:
        entries = []
        kept[_key(path)] = set()
        for stored, found in refs[_key(path)][1]:
            name = os.path.basename(path)
            if not found or not os.path.exists(found):
                warnings.append(f"{name} references {os.path.basename(stored)}, which can't be found anywhere. "
                                "That reference is left as it is.")
                kept[_key(path)].add(_key(stored))
                continue
            target = known.get(_key(found))
            if target is None:
                external.append((path, found))
                kept[_key(path)].add(_key(stored))
                continue
            if _key(stored) != _key(found) and os.path.exists(stored):
                warnings.append(f"{name} says it uses {stored}, but SolidWorks finds {found}. "
                                "Check that the copy uses the file you expect.")
            entries.append((stored, target))
        repoints[_key(path)] = entries
    if external and not allow_external:
        lines = sorted({f"{os.path.basename(p)} -> {ref}" for p, ref in external})
        more = f"\n...and {len(lines) - 8} more" if len(lines) > 8 else ""
        raise ExternalReferences(
            f"{len(lines)} reference(s) point at files that are not part of this import:\n"
            + "\n".join(lines[:8]) + more +
            "\n\nInclude those files in the import, or go ahead anyway (the copies would still depend on "
            "the original files).", sorted({(p, ref) for p, ref in external}))
    if external:
        warnings.append(f"{len(external)} reference(s) were left pointing at files outside the import.")
    return Plan(items=items, specs=specs, pns=pns, copies={p: copies[_key(p)] for p in order}, order=order,
                repoints=repoints, external=external, warnings=warnings, kept=kept)


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------

def _check_cancel(cancel):
    if cancel is not None and cancel():
        raise ImportCancelled("The import was cancelled. Nothing was added to the vault.")


def _copy_everything(repo, plan, backend, cancel, progress, log):
    total = len(plan.order)
    for number, path in enumerate(plan.order, start=1):
        _check_cancel(cancel)
        new_path = plan.copies[path]
        if progress:
            progress(number, total, f"Copying {os.path.basename(path)} as {os.path.basename(new_path)}")
        backend.copy(path, new_path)
        if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
            raise ImportFailed(f"The copy {new_path} was not created properly.")
        for stored, target in plan.repoints[_key(path)]:
            if not backend.repoint(new_path, stored, target):
                raise ImportFailed(f"SolidWorks would not change the reference to {os.path.basename(stored)} "
                                   f"inside {os.path.basename(new_path)}.")


def _verify(repo, plan, backend, before, log):
    """The copies must reference only each other, and the originals must be untouched."""
    cad = registry.cad_dir(repo)
    for path in plan.order:
        new_path = plan.copies[path]
        if not os.path.exists(new_path):
            raise ImportFailed(f"Missing after copying: {new_path}")
        for stored, _found in backend.references(new_path):
            if is_inside(stored, cad) or _key(stored) in plan.kept[_key(path)]:
                continue
            raise ImportFailed(f"{os.path.basename(new_path)} still references {stored}, outside the vault.")
    changed = [p for p, snap in before.items() if snap != _snapshot([p])[p]]
    if changed:
        raise ImportFailed("These original files changed while importing, which should never happen, so the "
                           "import was undone:\n" + "\n".join(changed[:8]))


# ---------------------------------------------------------------------------
# Part numbers: proposing them, editing them, checking them
#
# An import PROPOSES numbers a little way ahead of the lowest free part number (the gap, plus a random extra so two
# big imports started at the same moment are unlikely to land on the same numbers), counting up from the vault's
# start number and round again from 1 once past the highest the digits allow. Nothing is reserved or pushed. The
# numbers are checked again, for real, when you finish; any that Litterbox chose and someone else has taken are
# replaced by the next free ones.
# ---------------------------------------------------------------------------



DEFAULT_GAP = 100           # propose numbers this far past the lowest free part number
DEFAULT_JITTER = 100        # plus up to this many more at random


@dataclass
class Entry:
    """One row of the import table."""
    item: object                    # the manifest Item
    pn: PN
    name: str
    description: str = ""
    manual: bool = False            # True once the user typed this part number


@dataclass
class Conflict:
    index: int                      # row in the table (0-based)
    pn: PN
    reason: str
    manual: bool                    # True: the user typed it, so the user has to change it


@dataclass
class Refresh:
    renumbered: list = field(default_factory=list)      # (row, old PN, new PN) for automatic numbers that were taken
    conflicts: list = field(default_factory=list)       # Conflicts left, which are always typed-in numbers


class PNConflict(ImportFailed):
    """Typed-in part numbers are taken. Nothing was changed; the user should fix the highlighted rows."""

    def __init__(self, message, conflicts, renumbered=()):
        super().__init__(message)
        self.conflicts = list(conflicts)
        self.renumbered = list(renumbered)


@dataclass
class Proposal:
    """The import table: one Entry per item, in order. The GUI edits these and shows `conflicts` in red."""
    entries: list
    org: str = ""
    note: str = ""                  # where the proposed numbers start and why, for the window's status line
    family: object = None           # a base number: every automatic row is a variant of it (None: separate numbers)

    def set_pn(self, index, text):
        """The user typed a part number into row `index`. Raises ImportFailed if it isn't a valid one."""
        try:
            new = pn_module.parse(str(text).strip())
            pn_module.check_new_base(new.base)
            pn_module.check_variant(new.variant)
        except pn_module.PNError as e:
            raise ImportFailed(f"Row {index + 1}: {e}") from None
        entry = self.entries[index]
        entry.pn, entry.manual = new, True

    def reset_pn(self, index):
        """Hand the row back to Litterbox: it gets an automatic number again at the next refresh."""
        self.entries[index].manual = False

    def pns(self):
        return [e.pn for e in self.entries]


def _used_numbers(repo, org):
    existing = registry.list_pns(repo, org)
    return set(existing), {pn.base for pn in existing}


def pick_block(repo, count, org, gap=DEFAULT_GAP, jitter=DEFAULT_JITTER, rng=None):
    """`count` part numbers (variant 001) to propose: the free ones starting `gap` places (plus a random extra of up
    to `jitter`) past the LOWEST free part number, which is not the same as above the highest one in use. Numbers
    count up from the vault's start number and, past the highest the digits allow, round again from 1."""
    _taken, bases = _used_numbers(repo, org)
    start = config.get_start_number(repo)
    lowest = pn_module.free_bases(bases, 1, start)
    if not lowest:
        raise ImportFailed(f"The vault does not have {count} free part numbers left.")
    extra = (rng or random).randrange(jitter) if jitter > 0 and gap > 0 else 0
    first = pn_module.base_after(lowest[0], max(gap, 0) + extra, start)
    free = pn_module.free_bases(bases, count, first)
    if len(free) < count:
        raise ImportFailed(f"The vault does not have {count} free part numbers left.")
    return [PN(org, b, 1) for b in free]


def _family_free_variants(repo, proposal, skip=()):
    """The variant numbers of the family base that nothing is using: not in the vault, and not typed into a row."""
    base, org = proposal.family, proposal.org
    used = {pn.variant for pn in registry.list_pns(repo, org) if pn.base == base}
    used |= {e.pn.variant for i, e in enumerate(proposal.entries)
             if e.manual and e.pn.base == base and i not in skip}
    return [v for v in range(pn_module.MIN_VARIANT, pn_module.MAX_VARIANT + 1) if v not in used]


def _family_shortage(base, wanted, free):
    return (f"Part number {pn_module.format_base(base)} only has {free} unused variant number(s) "
            f"(the most a part number can have is {pn_module.MAX_VARIANT}), but {wanted} part(s) are being imported "
            f"to it. Choose another number, or import fewer parts at a time.")


def set_family(repo, proposal, base, sync=True):
    """Import every automatic row as a variant of one base number (`base`), or back to separate numbers (None).

    If the base is already in use the new variants start from the lowest unused ones. Raises ImportFailed, leaving
    the table as it was, if the base is not valid or does not have enough unused variants for the rows."""
    if base is None:
        count = sum(1 for e in proposal.entries if not e.manual)
        if proposal.family is None:
            return
        if sync:
            try:
                create.sync_latest(repo)
            except create.CreateError as e:
                raise ImportFailed(str(e)) from None
        proposal.family = None
        if count:
            for entry, pn in zip((e for e in proposal.entries if not e.manual), pick_block(repo, count, proposal.org)):
                entry.pn = pn
        return
    try:
        base = pn_module.check_new_base(base)
    except pn_module.PNError as e:
        raise ImportFailed(str(e)) from None
    if sync:
        try:
            create.sync_latest(repo)
        except create.CreateError as e:
            raise ImportFailed(str(e)) from None
    previous = proposal.family
    proposal.family = base
    automatic = [e for e in proposal.entries if not e.manual]
    free = _family_free_variants(repo, proposal)
    if len(free) < len(automatic):
        proposal.family = previous
        raise FamilyFull(_family_shortage(base, len(automatic), len(free)))
    for entry, variant in zip(automatic, free):
        entry.pn = PN(proposal.org, base, variant)


def check_proposal(repo, proposal):
    """Conflicts in the table right now (reads the local copy; call sync first for the latest)."""
    org = proposal.org
    taken, _bases = _used_numbers(repo, org)
    claimed, conflicts = {}, []
    order = [i for i, e in enumerate(proposal.entries) if e.manual] + \
            [i for i, e in enumerate(proposal.entries) if not e.manual]
    for index in order:
        entry = proposal.entries[index]
        if entry.pn.org != org:
            reason = f"{entry.pn} is for a different organization (this vault uses {org})."
        elif entry.pn in taken:
            try:
                holder = registry.load(repo, entry.pn)
                reason = f"{entry.pn} is already used by '{holder.name}'."
            except registry.RegistryError:
                reason = f"{entry.pn} is already used."
        elif entry.pn in claimed:
            reason = f"{entry.pn} is used twice in this import (rows {claimed[entry.pn] + 1} and {index + 1})."
        else:
            claimed[entry.pn] = index
            continue
        conflicts.append(Conflict(index, entry.pn, reason, entry.manual))
    return sorted(conflicts, key=lambda c: c.index)


def _renumber_automatic(repo, proposal, conflicts):
    """Give every automatic row that conflicts a new, free number near the rest of the proposed block. Returns the changes."""
    if proposal.family is not None:
        return _renumber_family(repo, proposal, conflicts)
    taken, bases = _used_numbers(repo, proposal.org)
    in_use = {e.pn.base for i, e in enumerate(proposal.entries) if i not in {c.index for c in conflicts if not c.manual}}
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    bad = [c for c in conflicts if not c.manual]
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    near = min(automatic, default=config.get_start_number(repo))          # stay near the proposed block
    free = pn_module.free_bases(bases | in_use, len(bad), near)
    if len(free) < len(bad):
        raise ImportFailed("The vault has run out of part numbers for this import.")
    changes = []
    for conflict, candidate in zip(bad, free):
        entry = proposal.entries[conflict.index]
        changes.append((conflict.index, entry.pn, PN(proposal.org, candidate, 1)))
        entry.pn = PN(proposal.org, candidate, 1)
    return changes


def _renumber_family(repo, proposal, conflicts):
    """Family mode: an automatic row whose variant was taken gets the next unused variant of the base."""
    bad = {c.index for c in conflicts if not c.manual}
    keep = {e.pn.variant for i, e in enumerate(proposal.entries)
            if i not in bad and e.pn.base == proposal.family}
    free = [v for v in _family_free_variants(repo, proposal, skip=bad) if v not in keep]
    if len(free) < len(bad):
        raise FamilyFull(_family_shortage(proposal.family, len(proposal.entries), len(free) + len(keep)))
    changes = []
    for index, variant in zip(sorted(bad), free):
        entry = proposal.entries[index]
        new = PN(proposal.org, proposal.family, variant)
        changes.append((index, entry.pn, new))
        entry.pn = new
    return changes


def refresh(repo, proposal, log=print):
    """Download the newest records, replace automatic numbers that are now taken, and report what is left.

    Typed-in numbers are never changed: if they are taken they are returned in `conflicts`
    (the table shows those rows in red) and the user decides what to do.
    """
    try:
        create.sync_latest(repo)
    except create.CreateError as e:
        raise ImportFailed(str(e)) from None
    renumbered = []
    for _round in range(5):
        conflicts = check_proposal(repo, proposal)
        automatic = [c for c in conflicts if not c.manual]
        if not automatic:
            break
        renumbered += _renumber_automatic(repo, proposal, conflicts)
    for row, old, new in renumbered:
        log(f"Row {row + 1}: {old} was taken, so it now gets {new}.")
    return Refresh(renumbered, [c for c in check_proposal(repo, proposal) if c.manual])


# ---------------------------------------------------------------------------
# Preparing (slow reading, no writing) and finishing (the real import)
# ---------------------------------------------------------------------------

@dataclass
class Prepared:
    manifest: object
    manifest_path: str
    candidates: list            # every manifest item that has no part number yet, included or not
    refs: dict
    proposal: Proposal
    backend: object
    owns_backend: bool
    version: str = ""
    allow_external: bool = False
    cots: bool = False          # Import COTS: every part in this import is recorded as purchased

    @property
    def items(self):
        """The items that will be imported: the ones in the table."""
        return [e.item for e in self.proposal.entries]

    def close(self):
        if self.owns_backend:
            self.backend.close()


def _free_pn(repo, proposal):
    """An unused part number for a row added to the table: just after the automatic ones already there."""
    if proposal.family is not None:
        used = {e.pn.variant for e in proposal.entries if e.pn.base == proposal.family}
        free = [v for v in _family_free_variants(repo, proposal) if v not in used]
        if not free:
            raise FamilyFull(_family_shortage(proposal.family, len(proposal.entries) + 1, len(proposal.entries)))
        return PN(proposal.org, proposal.family, free[0])
    _taken, bases = _used_numbers(repo, proposal.org)
    here = {e.pn.base for e in proposal.entries}
    automatic = [e.pn.base for e in proposal.entries if not e.manual]
    if automatic:                                       # just after the numbers already proposed
        free = pn_module.free_bases(bases | here, 1, max(automatic) + 1)
    else:
        free = [pick_block(repo, 1, proposal.org)[0].base]
    if not free:
        raise ImportFailed("The vault has run out of part numbers for this import.")
    return PN(proposal.org, free[0], 1)


def set_included(repo, prepared, item_id, include):
    """Tick or untick one item (by its manifest id): adds or removes its row in the table."""
    item = next((i for i in prepared.candidates if i.id == item_id), None)
    if item is None:
        raise ImportFailed(f"There is no item {item_id} left to import.")
    entries = prepared.proposal.entries
    present = next((e for e in entries if e.item is item), None)
    if not include:
        if present:
            entries.remove(present)
        item.include = False
        return
    if present:
        return
    missing = [f.path for f in item.files if not os.path.isfile(f.path)]
    if missing:
        raise ImportFailed(f"Can't include '{item.name}': {missing[0]} can't be found.")
    if _key(item.main_path) not in prepared.refs:
        raise ImportFailed(f"Can't include '{item.name}': its references were not read.")
    position = prepared.candidates.index(item)
    before = sum(1 for e in entries if prepared.candidates.index(e.item) < position)
    entries.insert(before, Entry(item, _free_pn(repo, prepared.proposal), item.name, item.description))
    item.include = True


def prepare(repo, manifest_path, backend=None, allow_external=False, cancel=None, progress=None,
            log=print, org=None, gap=DEFAULT_GAP, jitter=DEFAULT_JITTER, rng=None, cots=False):
    """Check the manifest, read every file's references, refresh the vault and propose part numbers.

    Writes nothing to the vault. Returns a Prepared with a `proposal` (the table to show).
    Call close() on it when done, whether or not the import went ahead.
    """
    eng.validate_repo(repo)
    status = recover(repo, log)
    if status != "nothing":
        log(f"(An earlier import was interrupted; it was dealt with: {status}.)")
    try:
        mf = manifest_module.load(manifest_path)
    except manifest_module.ManifestError as e:
        raise ImportFailed(str(e)) from None
    found_problems = manifest_module.problems(mf)
    if found_problems:
        raise ImportFailed("The manifest needs fixing first:\n" + "\n".join(found_problems[:10]))
    items = manifest_module.pending_items(mf)
    if not items:
        raise ImportFailed("There is nothing left to import: every included item already has a part number.")
    missing = [p for item in items for p in _item_files(item) if not os.path.isfile(p)]
    if missing:
        raise ImportFailed(f"{len(missing)} file(s) in the manifest can't be found:\n" + "\n".join(missing[:8]))
    # References are read for every item that could be ticked later, so ticking is instant.
    candidates = [i for i in mf.items if not i.pn]
    readable = [i for i in candidates if all(os.path.isfile(p) for p in _item_files(i))]
    for item in items:
        if _extension(item.main_path) not in MODEL_EXTENSIONS | {DRAWING_EXTENSION}:
            raise ImportFailed(f"Item {item.id}: {item.main_path} is not a SolidWorks file.")

    owns_backend = backend is None
    backend = backend or SolidWorksBackend()
    try:
        version = backend.version()
        if version:
            log(f"SolidWorks version {version}. (Copies are not re-saved, but anyone opening them later "
                "needs a SolidWorks at least as new as the originals.)")
        refs = read_references(readable, backend, progress, cancel)
        try:
            create.sync_latest(repo)                               # the newest list of part numbers
            org = create._org(repo, org)
            block = pick_block(repo, len(items), org, gap, jitter, rng)
        except (create.CreateError, config.ConfigError, registry.RegistryError) as e:
            raise ImportFailed(str(e)) from None
        proposal = Proposal([Entry(item, pn, item.name, item.description) for item, pn in zip(items, block)], org)
        _taken, bases = _used_numbers(repo, org)
        proposal.note = (f"Proposed part numbers start at {pn_module.format_base(block[0].base)}. This vault's start number is "
                         f"{pn_module.format_base(config.get_start_number(repo))}; the highest part number in use is "
                         + (pn_module.format_base(max(bases)) if bases else "(none yet)") + ". "
                         + config.explain_start_number(repo))
        return Prepared(mf, str(manifest_path), candidates, refs, proposal, backend, owns_backend, version,
                        allow_external, cots)
    except BaseException:
        if owns_backend:
            backend.close()
        raise


def _conflict_message(conflicts):
    lines = [f"Row {c.index + 1}: {c.reason}" for c in conflicts]
    return ("These part numbers can't be used. Nothing was imported; change them and finish again:\n"
            + "\n".join(lines))


def finish(repo, prepared, dry_run=False, cancel=None, progress=None, log=print):
    """Do the import with the table as it stands. Returns a Result.

    First the part numbers are checked against the newest records. Automatic numbers that are
    taken are replaced by free ones; if a number the user typed is taken, PNConflict is raised
    before anything is copied (the table can be corrected and finish called again). Cancelling,
    errors and crashes leave nothing behind (see the top of this file).
    """
    mf, backend, proposal = prepared.manifest, prepared.backend, prepared.proposal
    items = prepared.items
    if not items:
        raise ImportFailed("Nothing is selected, so there is nothing to import.")
    originals = _snapshot([p for item in items for p in _item_files(item)])
    last_error = None
    renumbered = []
    for attempt in range(1, ATTEMPTS + 1):
        _check_cancel(cancel)
        state = refresh(repo, proposal, log)
        renumbered += state.renumbered
        if state.conflicts:
            raise PNConflict(_conflict_message(state.conflicts), state.conflicts, renumbered)
        try:
            specs = create.clean_specs([
                create.PartSpec(name=e.name, description=e.description, cots=prepared.cots or e.item.cots,
                                imported=True, import_path=e.item.main_path) for e in proposal.entries])
        except create.CreateError as e:
            raise ImportFailed(str(e)) from None
        pns = proposal.pns()
        plan = build_plan(repo, items, specs, pns, prepared.refs, mf, prepared.allow_external)
        if dry_run:
            return Result(pns=pns, warnings=plan.warnings, plan=plan, dry_run=True, version=prepared.version,
                          renumbered=renumbered)

        new_files = [_relative(repo, plan.copies[p]) for p in plan.order]
        record_paths = [eng.record_relpath(pn) for pn in pns]
        token = uuid.uuid4().hex[:12]
        noun = "COTS parts" if prepared.cots else "parts"
        message = ((f"Imported {len(pns)} {noun}: {min(pns)} to {max(pns)}" if len(pns) > 1
                    else f"{pns[0]}: Imported{' COTS' if prepared.cots else ''} - {specs[0].name}")
                   + f"\n\nLitterbox-Import: {token}")
        _write_journal(repo, "copying", token, new_files, record_paths)
        try:
            _copy_everything(repo, plan, backend, cancel, progress, log)
            _verify(repo, plan, backend, originals, log)
            _check_cancel(cancel)
            if progress:
                progress(len(plan.order), len(plan.order), "Adding to the vault...")
            _write_journal(repo, "committing", token, new_files, record_paths)
            create.create_planned(repo, specs, pns, extra_paths=new_files, message=message)
        except create.NumbersTaken as e:
            last_error = e
            recover(repo, log)
            log(f"Someone else used one of the part numbers just now (try {attempt} of {ATTEMPTS}); checking again.")
            continue
        except BaseException:
            recover(repo, log)          # removes exactly what this import copied
            raise
        _clear_journal(repo)
        eng.enforce_read_only(repo)
        for entry in proposal.entries:                      # the manifest keeps any edits made in the table
            entry.item.name, entry.item.description = entry.name, entry.description
        manifest_module.record_assignments(mf, items, pns)
        try:
            manifest_module.save(mf, prepared.manifest_path)
        except manifest_module.ManifestError as e:
            plan.warnings.append(f"The parts were imported, but the manifest could not be updated: {e}")
        return Result(pns=pns, files=new_files, warnings=plan.warnings, plan=plan, version=prepared.version,
                      renumbered=renumbered)
    raise ImportFailed(f"Part numbers kept being taken by other people. Nothing was imported. "
                       f"Try again.\n\n{last_error}")


def run(repo, manifest_path, backend=None, dry_run=False, allow_external=False, cancel=None,
        progress=None, log=print, org=None, gap=DEFAULT_GAP, jitter=DEFAULT_JITTER, rng=None, cots=False):
    """prepare() and finish() in one go, with the proposed numbers and names as they are (no table to edit).

    Raises ImportFailed (ImportCancelled if cancelled; PNConflict never happens here because
    nothing is typed in) with nothing left behind.
    """
    prepared = prepare(repo, manifest_path, backend, allow_external, cancel, progress, log, org, gap, jitter, rng, cots)
    try:
        return finish(repo, prepared, dry_run, cancel, progress, log)
    finally:
        prepared.close()


# ---------------------------------------------------------------------------
# Duplicates (Import COTS warns about these; it never blocks)
# ---------------------------------------------------------------------------

def _sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicates(repo, prepared):
    """{row index: [warning, ...]} for rows that look like a part Litterbox already has.

    A row is a likely duplicate when
      * a file in the vault's cad folder has exactly the same contents as the row's main file, or
      * a part with exactly the same Name is already in the vault, or
      * another row of this same import has the same file contents or the same Name.
    Only a warning: the caller decides what to do. Reads the local copy of the vault; sync first for the newest.
    Vault files are only read when their size matches, so this stays quick on a big vault.
    """
    entries = prepared.proposal.entries
    org = prepared.proposal.org
    found = {}

    def warn(index, text):
        found.setdefault(index, []).append(text)

    # names already in the vault
    by_name = {}
    for pn in registry.list_pns(repo, org):
        try:
            by_name.setdefault(registry.load(repo, pn).name, []).append(pn)
        except registry.RegistryError:
            continue

    # same contents: only look at vault files whose size and type match
    wanted = {}
    for index, entry in enumerate(entries):
        main = entry.item.files[0]
        try:
            size = os.path.getsize(main.path)
        except OSError:
            continue
        wanted.setdefault((size, _extension(main.path)), []).append(index)
    hashes = {}
    for pn, revisions in registry.cad_index(repo).items():
        for rel in sorted(f for files in revisions.values() for f in files):
            path = Path(repo) / rel
            try:
                key = (path.stat().st_size, _extension(rel))
            except OSError:
                continue
            if key not in wanted:
                continue
            try:
                hashes.setdefault(_sha256(path), []).append(pn)
            except OSError:
                continue
    digests = {}
    for index, entry in enumerate(entries):
        main = entry.item.files[0]
        if (os.path.getsize(main.path) if os.path.isfile(main.path) else -1, _extension(main.path)) not in wanted:
            continue
        digest = main.sha256 or _sha256(main.path)
        digests[index] = digest
        for pn in hashes.get(digest, []):
            warn(index, f"The file is identical to the one in the vault for {pn}.")

    for index, entry in enumerate(entries):
        for pn in by_name.get(entry.name, []):
            warn(index, f"A part with exactly this name already exists: {pn}.")
    names, same_file = {}, {}
    for index, entry in enumerate(entries):
        names.setdefault(entry.name, []).append(index)
        if index in digests:
            same_file.setdefault(digests[index], []).append(index)
    for group, what in (*((rows, "name") for rows in names.values()), *((rows, "file") for rows in same_file.values())):
        if len(group) > 1:
            for index in group:
                others = ", ".join(str(i + 1) for i in group if i != index)
                warn(index, f"Row {others} in this import has the same {what}.")
    return found


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: import files from a manifest")
    parser.add_argument("repo", help="path to the vault folder")
    parser.add_argument("manifest", nargs="?", help="the manifest file made by scan.py")
    parser.add_argument("--dry-run", action="store_true", help="check everything and show the plan; write nothing")
    parser.add_argument("--allow-external", action="store_true",
                        help="allow references to files that are not part of the import")
    parser.add_argument("--gap", type=int, default=DEFAULT_GAP,
                        help=f"propose part numbers this far past the lowest free one (default {DEFAULT_GAP})")
    parser.add_argument("--cots", action="store_true", help="record every imported part as COTS (purchased)")
    parser.add_argument("--recover", action="store_true", help="clean up after an interrupted import and stop")
    args = parser.parse_args(argv)
    try:
        if args.recover:
            print(f"Recovery: {recover(args.repo)}")
            return 0
        if not args.manifest:
            parser.error("the manifest file is required")
        result = run(args.repo, args.manifest, dry_run=args.dry_run, allow_external=args.allow_external, gap=args.gap, cots=args.cots,
                     progress=lambda done, total, text: print(f"[{done}/{total}] {text}"))
    except eng.LitterboxError as e:
        print(f"\nERROR: {e}")
        return 1
    if result.dry_run:
        print(f"\nDry run: {len(result.pns)} part(s) would be created, {len(result.plan.order)} file(s) copied.")
        for item, pn in zip(result.plan.items, result.pns):
            print(f"  {pn}  {item.name}")
    else:
        print(f"\nImported {len(result.pns)} part(s), {len(result.files)} file(s): {min(result.pns)} to {max(result.pns)}")
    for warning in result.warnings:
        print(f"  note: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
