"""
references.py - which parts an assembly uses, where a part is used, and keeping those up to date.

Each assembly's PN record lists the parts that each of its revisions uses:

    references:
      A:
      - HCR-00005-001_A
      - HCR-00006-001_B

Litterbox reads them from the assembly file (through SolidWorks) every time the assembly is checked
in, and again when a new revision is made. Because a released part never changes, "the assembly uses
HCR-00006-001_B" always means exactly the same files, forever.

WHERE USED   every assembly revision (released or not) that uses a part.
STALE        a reference is stale when the part has a newer RELEASED revision than the one the
             assembly uses. It is also flagged when the revision used is not released yet, was
             cancelled, or the part was voided or has no record.
REPLACE      Litterbox can point an assembly that is still in work at the latest released revision of
             parts it uses. Released assemblies are frozen: to change one, revise it.
"""

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from litterbox.parts import engine as eng
from litterbox.core import pn as pn_module
from litterbox.records import registry
from litterbox.core.pn import PN
from litterbox.errors import LitterboxError

MODEL_EXTENSIONS = (".sldprt", ".sldasm")
ASSEMBLY_EXTENSIONS = (".sldasm",)

# Why a reference is flagged
OK = "ok"
STALE = "stale"                 # a newer revision of the part has been released
UNRELEASED = "unreleased"       # the revision used is not released yet
CANCELLED = "cancelled"         # the revision used was cancelled: its files are gone from cad
VOID = "void"
MISSING = "missing"             # there is no record for the part

STATE_TEXT = {
    OK: "OK",
    STALE: "Newer revision released",
    UNRELEASED: "Not released yet",
    CANCELLED: "Revision was cancelled",
    VOID: "Part was voided",
    MISSING: "Part not found",
}

# Release rule (config.yaml: release_rule)
RULE_WARN, RULE_BLOCK, RULE_OFF = "warn", "block", "off"


class ReferencesError(LitterboxError):
    """Something went wrong reading or changing references."""


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def split_stem(stem):
    """'HCR-00005-001_B' -> (PN, 'B'), or None if it is not a Litterbox name."""
    parsed = pn_module.try_parse_filename(f"{stem}.X")
    if parsed is None:
        return None
    return parsed[0], parsed[1]


def stem_of_path(path):
    """The Litterbox 'HCR-00005-001_B' of a file path, or None for any other file."""
    parsed = pn_module.try_parse_filename(str(path))
    if parsed is None:
        return None
    return pn_module.file_stem(parsed[0], parsed[1])


def _name(path):
    return PurePosixPath(str(path).replace("\\", "/")).name


def _ext(path):
    return PurePosixPath(str(path).replace("\\", "/")).suffix.lower()


@contextlib.contextmanager
def _com_thread():
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pythoncom = None
    try:
        yield
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _new_backend(attach_only=False):
    from litterbox.importing import importer
    return importer.SolidWorksBackend(attach_only=attach_only)


# ---------------------------------------------------------------------------
# Reading references out of assembly files
# ---------------------------------------------------------------------------

def read_assembly_references(repo, pn, revision, backend, files=None):
    """The Litterbox parts that this revision's assembly files use, as a sorted list like
    ['HCR-00005-001_A']. Parts are not assemblies, so a revision with no .SLDASM gives [].
    Files that are not Litterbox files (a screw from a library, say) are ignored."""
    own = pn_module.file_stem(pn, revision)
    found = set()
    for rel in files if files is not None else registry.cad_files(repo, pn, revision):
        if _ext(rel) not in ASSEMBLY_EXTENSIONS:
            continue
        for stored, located in backend.references(os.path.join(str(repo), rel)):
            stem = stem_of_path(stored) or stem_of_path(located)
            if stem and stem.lower() != own.lower():
                found.add(stem)
    return sorted(found, key=str.lower)


def make_reader(backend=None, log=None):
    """A function to hand to engine.checkin(): reads an assembly's references when its files changed.

    reader(repo, pn, revision, changed_files) -> list of stems, or None (nothing to update)
    A SolidWorks that can't be reached gives a warning and None: the check-in still goes ahead.
    Without a backend it attaches to a SolidWorks that is already running and never starts one; if
    none is running the references are simply not updated this time.
    """
    log = log or (lambda text: None)

    def reader(repo, pn, revision, changed_files):
        if not any(_ext(f) in ASSEMBLY_EXTENSIONS for f in changed_files):
            return None
        mine = None
        try:
            with _com_thread():
                use = backend
                if use is None:
                    use = mine = _new_backend(attach_only=True)
                try:
                    return read_assembly_references(repo, pn, revision, use)
                finally:
                    if mine is not None:
                        mine.close()
        except Exception as e:
            log(f"WARNING: could not read what {pn} uses, so its references were not updated. {e}")
            return None

    return reader


# ---------------------------------------------------------------------------
# Looking things up
# ---------------------------------------------------------------------------

class LazyRecords:
    """Looks records up by PN as they are needed (None for a missing or unreadable one)."""

    def __init__(self, repo):
        self.repo, self.cache = repo, {}

    def get(self, pn, default=None):
        if pn not in self.cache:
            try:
                self.cache[pn] = registry.load(self.repo, pn)
            except registry.RegistryError:
                self.cache[pn] = None
        return self.cache[pn] or default


def load_records(repo):
    """{PN: Record} for every readable record."""
    records = {}
    for pn in registry.list_pns(repo):
        try:
            records[pn] = registry.load(repo, pn)
        except registry.RegistryError:
            continue
    return records


@dataclass
class Use:
    """One reference: `parent` (at `parent_revision`) uses `child` at `child_revision`."""
    parent: PN
    parent_revision: str
    child: PN
    child_revision: str
    state: str                      # OK, STALE, ...
    latest_released: str = ""       # the child's latest released revision ('' if none)
    parent_name: str = ""
    child_name: str = ""
    parent_status: str = ""         # status of THAT revision of the parent: in_work / released
    editable: bool = False          # the parent revision is in work, so it can be pointed at a newer part

    @property
    def state_text(self):
        text = STATE_TEXT[self.state]
        if self.state == STALE:
            text += f" (Rev {self.latest_released})"
        return text

    @property
    def replaceable(self):
        """Can Litterbox point this reference at the child's latest released revision?"""
        return (self.editable and bool(self.latest_released)
                and self.state in (STALE, CANCELLED)
                and self.latest_released != self.child_revision)


def classify(child_record, revision):
    """(state, latest released revision) of one use of a part at one revision."""
    if child_record is None:
        return MISSING, ""
    latest = child_record.released_revision
    if child_record.status == registry.STATUS_VOID:
        return VOID, latest
    if revision in registry.cancelled_revisions(child_record):
        return CANCELLED, latest
    number = pn_module.revision_number(revision)
    if latest and pn_module.revision_number(latest) > number:
        return STALE, latest
    if not latest or number > pn_module.revision_number(latest):
        if child_record.cots:
            return OK, latest
        return UNRELEASED, latest
    return OK, latest


def _parent_revision_status(record, revision):
    if revision == record.revision:
        return record.status
    return registry.STATUS_RELEASED         # earlier revisions are always released


def _use(records, parent_record, revision, stem):
    parts = split_stem(stem)
    if parts is None:
        return None
    child, child_revision = parts
    child_record = records.get(child)
    state, latest = classify(child_record, child_revision)
    status = _parent_revision_status(parent_record, revision)
    editable = (revision == parent_record.revision and status == registry.STATUS_IN_WORK
                and not parent_record.cots)
    return Use(parent_record.pn, revision, child, child_revision, state, latest,
               parent_record.name, child_record.name if child_record else "", status, editable)


def uses(repo, pn, revision=None, records=None):
    """What the part's assembly (at `revision`, default the working one) uses: a list of Use."""
    records = records if records is not None else LazyRecords(repo)
    pn = eng._as_pn(pn)
    record = records.get(pn)
    if record is None:
        raise ReferencesError(f"There is no record for {pn}.")
    revision = revision or record.revision
    found = [_use(records, record, revision, stem) for stem in record.references.get(revision, [])]
    return sorted((u for u in found if u), key=lambda u: (str(u.child), u.child_revision))


def where_used(repo, pn, records=None):
    """Every assembly revision that uses this part (any revision of it): a list of Use."""
    records = records if records is not None else load_records(repo)
    pn = eng._as_pn(pn)
    found = []
    for parent_record in records.values():
        for revision, stems in parent_record.references.items():
            for stem in stems:
                parts = split_stem(stem)
                if parts and parts[0] == pn:
                    found.append(_use(records, parent_record, revision, stem))
    return sorted((u for u in found if u),
                  key=lambda u: (str(u.parent), pn_module.revision_number(u.parent_revision), u.child_revision))


def stale_uses(repo, pn, records=None):
    """The references of the part's working revision that are not OK."""
    return [u for u in uses(repo, pn, None, records) if u.state != OK]


def stale_everywhere(repo, records=None):
    """Every reference, in every assembly still in work, that Litterbox could point at a newer revision."""
    records = records if records is not None else load_records(repo)
    found = []
    for record in records.values():
        if record.status == registry.STATUS_IN_WORK and not record.cots:
            found.extend(u for u in uses(repo, record.pn, None, records) if u.replaceable)
    return found


# ---------------------------------------------------------------------------
# The release rule
# ---------------------------------------------------------------------------

def needs_update(repo, record):
    """Revisions of this part whose list of parts used is missing or out of date."""
    return [rev for rev, files in registry.cad_index(repo).get(record.pn, {}).items()
            if registry.references_need_update(record, rev, files)]


def outdated_parts(repo, records=None):
    """Every part in the vault whose list of parts used is missing or out of date."""
    records = records if records is not None else load_records(repo)
    index = registry.cad_index(repo)
    return sorted(pn for pn, record in records.items()
                  if any(registry.references_need_update(record, rev, files)
                         for rev, files in index.get(pn, {}).items()))


def release_warnings(repo, pn, records=None):
    """Sentences about references that make a release a bad idea (empty if none)."""
    problems = []
    record = (records or LazyRecords(repo)).get(eng._as_pn(pn))
    if record is not None and needs_update(repo, record):
        problems.append("The list of parts it uses is out of date, so these checks may be wrong. "
                        "Use References... then Update references.")
    for use in uses(repo, pn, None, records):
        if use.state == OK:
            continue
        what = f"{use.child} Rev {use.child_revision}"
        if use.state == STALE:
            problems.append(f"It uses {what}, but Rev {use.latest_released} has been released since.")
        elif use.state == UNRELEASED:
            problems.append(f"It uses {what}, which has not been released.")
        elif use.state == CANCELLED:
            problems.append(f"It uses {what}, whose revision was cancelled.")
        elif use.state == VOID:
            problems.append(f"It uses {what}, which was voided.")
        else:
            problems.append(f"It uses {what}, which has no record in the vault.")
    return problems


# ---------------------------------------------------------------------------
# Pointing assemblies at newer revisions
# ---------------------------------------------------------------------------

@dataclass
class Replacement:
    """Point `parent`'s working revision at the child's latest released revision."""
    parent: PN
    child: PN
    old_revision: str


@dataclass
class ReplaceResult:
    parent: PN
    status: str                 # done, left_checked_out, skipped, failed
    message: str = ""
    children: list = field(default_factory=list)


def replacements_from(uses_list):
    return [Replacement(u.parent, u.child, u.child_revision) for u in uses_list if u.replaceable]


def _model_file(repo, child, revision):
    models = [f for f in registry.cad_files(repo, child, revision) if _ext(f) in MODEL_EXTENSIONS]
    return models[0] if models else None


def _repoint_file(repo, rel, replacements, backend):
    """Change the references inside one assembly file. Returns how many were changed."""
    path = os.path.join(str(repo), rel)
    changed = 0
    for replacement, old_name, new_path in replacements:
        done = False
        for stored, located in backend.references(path):
            if _name(stored or located).lower() == old_name.lower():
                if not backend.repoint(path, stored, new_path):
                    raise ReferencesError(f"SolidWorks would not change the reference to {old_name} inside "
                                          f"{_name(rel)}.")
                done = True
        changed += done
    for replacement, old_name, _new in replacements:
        for stored, located in backend.references(path):
            if _name(stored or located).lower() == old_name.lower():
                raise ReferencesError(f"{_name(rel)} still refers to {old_name}.")
    return changed


def replace_references(repo, replacements, comment="Updated to the latest released parts", backend=None,
                       log=print):
    """Point assemblies that are still in work at the latest released revision of the parts they use.

    For each assembly: if nobody has it checked out, Litterbox checks it out, changes it, and checks it in
    (one commit each). If you already have it checked out, the change is made in your copy and left for you to
    check in. If someone else has it, it is skipped. A failure on one assembly never stops the others and
    never leaves it half done. All the check-outs share one download and all the check-ins share one upload.
    Returns a ReplaceResult per assembly.
    """
    eng.validate_repo(repo)
    by_parent = {}
    for item in replacements:
        by_parent.setdefault(item.parent, []).append(item)

    owns_backend = backend is None
    results = {}
    try:
        if owns_backend and by_parent:
            backend = _new_backend()
        reader = make_reader(backend, log)
        with _com_thread():
            _replace_in_all(repo, by_parent, comment, backend, reader, log, results)
    finally:
        if owns_backend and backend is not None:
            backend.close()
    return [results[parent] for parent in sorted(by_parent) if parent in results]


def _plan_replacement(repo, parent, items, locks):
    """What to change in one assembly, worked out before anything is locked. Returns a ReplaceResult if there is
    nothing to do (or it can't be done), else (revision, edits, names, user_checked_out)."""
    try:
        record = registry.load(repo, parent)
        if record.status != registry.STATUS_IN_WORK or record.cots:
            return ReplaceResult(parent, "skipped", f"Rev {record.revision} is {record.status}, so it can't be changed.")
        lock = locks.get(eng.record_relpath(parent).lower())
        if lock and lock[0] != "you":
            return ReplaceResult(parent, "skipped", f"Checked out by {lock[1]}.")

        edits, names = [], []
        for item in items:
            child_record = registry.load(repo, item.child)
            latest = child_record.released_revision
            if not latest or latest == item.old_revision:
                continue
            new_rel = _model_file(repo, item.child, latest)
            if new_rel is None:
                return ReplaceResult(parent, "failed", f"Rev {latest} of {item.child} has no model file here. "
                                                         "Run Get Latest.")
            if eng.is_pointer(Path(repo) / new_rel):
                return ReplaceResult(parent, "failed", f"{new_rel} has not been downloaded. Run Get Latest.")
            old_name = pn_module.filename(item.child, item.old_revision, _ext(new_rel))
            edits.append((item, old_name, os.path.join(str(repo), new_rel)))
            names.append(f"{item.child} Rev {item.old_revision} -> {latest}")
        if not edits:
            return ReplaceResult(parent, "skipped", "Nothing to change.")
        return record.revision, edits, names, bool(lock)
    except Exception as e:
        return ReplaceResult(parent, "failed", str(e))


def _replace_in_all(repo, by_parent, comment, backend, reader, log, results):
    jobs = {}
    try:
        locks = eng.get_locks(repo, strict=True)
    except LitterboxError as e:
        for parent in by_parent:
            results[parent] = ReplaceResult(parent, "failed", str(e))
        return
    for parent in sorted(by_parent):
        outcome = _plan_replacement(repo, parent, by_parent[parent], locks)
        if isinstance(outcome, ReplaceResult):
            results[parent] = outcome
        else:
            jobs[parent] = outcome

    ours = [parent for parent, job in jobs.items() if not job[3]]          # the ones we have to check out
    if ours:
        log("Checking out " + ", ".join(map(str, ours)) + " to update their references")
        try:
            _done, failed = eng.checkout_many(repo, ours)
        except Exception as e:
            failed = [(parent, str(e)) for parent in ours]
        for parent, why in failed:
            if parent in jobs:
                results[parent] = ReplaceResult(parent, "failed", why)
                del jobs[parent]
                ours.remove(parent)

    undo = []
    for parent, (revision, edits, names, user_checked_out) in list(jobs.items()):
        try:
            files = [f for f in registry.cad_files(repo, parent, revision) if _ext(f) in ASSEMBLY_EXTENSIONS]
            if not files:
                raise ReferencesError(f"{parent} has no assembly file in Rev {revision}.")
            changed = 0
            for rel in files:
                log(f"Updating {_name(rel)}")
                changed += _repoint_file(repo, rel, edits, backend)
            if not changed:
                raise ReferencesError("None of those parts are in the assembly file any more. Check In the assembly "
                                      "so its list of parts is refreshed.")
        except Exception as e:
            results[parent] = ReplaceResult(parent, "failed", str(e))
            del jobs[parent]
            if parent in ours:
                undo.append(parent)
                ours.remove(parent)
    if undo:
        try:
            eng.undo_checkout_many(repo, undo)
        except Exception as e:
            log(f"WARNING: could not undo the check-out of {', '.join(map(str, undo))}: {e}")

    for parent, (_revision, _edits, names, user_checked_out) in jobs.items():
        if user_checked_out:
            results[parent] = ReplaceResult(parent, "left_checked_out",
                                            "Changed in your copy. Check it in to save the change.", names)
    if ours:
        try:
            _done, failed = eng.checkin_many(repo, ours, comment, references_reader=reader)
        except Exception as e:
            failed = [(parent, str(e)) for parent in ours]
        failures = dict(failed)
        notice = failures.pop("Locks", None)          # saved, but a lock could not be released
        for parent in ours:
            if parent in failures:
                log(f"WARNING: the change to {parent} could not be checked in: {failures[parent]}")
                results[parent] = ReplaceResult(
                    parent, "left_checked_out",
                    f"Changed and still checked out to you, but the check-in failed: {failures[parent]}", jobs[parent][2])
            elif notice:
                results[parent] = ReplaceResult(parent, "left_checked_out", notice, jobs[parent][2])
            else:
                results[parent] = ReplaceResult(parent, "done", "Updated and checked in.", jobs[parent][2])


# ---------------------------------------------------------------------------
# Refreshing records for assemblies that came in another way (the importer)
# ---------------------------------------------------------------------------

def rescan(repo, pns=None, backend=None, log=print):
    """Read the references of assemblies straight from their files and store them in the records.

    Used by "Update references" and after an import. Covers every revision whose files are on disk.
    Each record is changed under its own lock and uploaded. A part that anyone has checked out, or
    whose files have not been downloaded, is skipped (the reason is in the result).
    Returns {PN: 'updated' | 'unchanged' | 'skipped: why'}.
    """
    eng.validate_repo(repo)
    owns = backend is None
    results, edits = {}, {}
    try:
        index = registry.cad_index(repo)
        locks = eng.get_locks(repo, strict=True)
        for pn in (pns or registry.list_pns(repo)):
            pn = eng._as_pn(pn)
            revisions = index.get(pn, {})
            if not any(_ext(f) in ASSEMBLY_EXTENSIONS for fs in revisions.values() for f in fs):
                continue
            lock = locks.get(eng.record_relpath(pn).lower())
            if lock:
                results[pn] = f"skipped: checked out by {'you' if lock[0] == 'you' else lock[1]}. Check it in first."
                log(f"{pn}: {results[pn]}")
                continue
            try:
                if backend is None:
                    backend = _new_backend()
                outcome = _rescan_one(repo, pn, revisions, backend)
            except LitterboxError as e:
                outcome = f"skipped: {e}"
            except Exception as e:
                outcome = f"skipped: {e}"
            if isinstance(outcome, tuple):
                edits[pn] = outcome[1]                     # saved all together below
            else:
                results[pn] = outcome
                log(f"{pn}: {results[pn]}")
        if edits:                                           # one download and one upload for every record
            try:
                batch = eng._edit_records(repo, [(pn, "checkin", edit, f"{pn}: Updated list of parts used")
                                                 for pn, edit in edits.items()])
                errors, notice = batch.errors, batch.notice
            except LitterboxError as e:
                errors, notice = {pn: e for pn in edits}, ""
            if notice:
                log(notice)
            for pn in edits:
                results[pn] = f"skipped: {errors[pn]}" if pn in errors else "updated"
                log(f"{pn}: {results[pn]}")
    finally:
        if owns and backend is not None:
            backend.close()
    return results


def _rescan_one(repo, pn, revisions, backend):
    found = {}
    with _com_thread():
        for revision, files in revisions.items():
            if not any(_ext(f) in ASSEMBLY_EXTENSIONS for f in files):
                continue
            for f in files:
                if eng.is_pointer(Path(repo) / f):
                    raise ReferencesError(f"{f} has not been downloaded. Run Get Latest.")
            found[revision] = read_assembly_references(repo, pn, revision, backend, files)
    current = registry.load(repo, pn)
    if all(current.references.get(rev) == sorted(set(stems), key=str.lower)
           and rev not in current.references_outdated for rev, stems in found.items()):
        return "unchanged"
    changed = []

    def edit(record, user):
        for revision, stems in found.items():
            if registry.set_references(record, stems, revision):
                changed.append(revision)
        return registry.add_event(record, "references_updated", user,
                                  references={rev: record.references.get(rev, []) for rev in changed})

    return "edit", edit
