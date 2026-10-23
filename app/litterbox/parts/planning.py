"""
planning.py - checking a part before Release or Make COTS: what would
be frozen, and what stands in the way (ReleasePlan).
"""

from dataclasses import dataclass, field

from litterbox import diagnostics
from litterbox.core import revision_letters
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import repository
from litterbox.git import runner
from litterbox.parts import batch_core
from litterbox.parts import toolbox_check
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.error_conversion import converts_errors
from litterbox.vault import config


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


class PlanContext:
    """What the checks on several parts share, so a batch looks at the vault once: one fetch, one lock list, one
    list of modified files, one look at the cad folder, one look at the commits not uploaded (or not got) yet, one
    set of records."""

    def __init__(self, repo, draft_ok=None):
        self.repo = repo
        self.draft_ok = draft_ok        # the id of the draft being resubmitted: its parts may go ahead
        self._fetched = False
        self._locks = self._modified = self._records = self._index = None
        self._changed_in = {}

    def fetch(self):
        if not self._fetched:
            self._fetched = True
            try:
                runner.run(["git", "fetch"], self.repo, quiet=True)
            except LitterboxError as e:
                diagnostics.LOG(f"WARNING: could not check the vault for newer changes. {e}")

    def locks(self):
        if self._locks is None:
            self._locks = lfs_locks.get_locks(self.repo, strict=True)
        return self._locks

    def modified(self):
        if self._modified is None:
            self._modified = repository.get_modified(self.repo)
        return self._modified

    def cad_index(self):
        if self._index is None:
            self._index = record_files.cad_index(self.repo)
        return self._index

    def changed_in(self, rev_range):
        """The paths the commits in rev_range change (repository.paths_changed_in); asked after the fetch."""
        if rev_range not in self._changed_in:
            self._changed_in[rev_range] = repository.paths_changed_in(self.repo, rev_range)
        return self._changed_in[rev_range]

    def records(self):
        if self._records is None:
            from litterbox.references import reference_model
            self._records = reference_model.LazyRecords(self.repo)
        return self._records


def blockers(repo, pn, record, verb, fetch, required=record_model.STATUS_IN_WORK, required_label="in-work",
              allow_pending=False, ctx=None):
    """Shared by release, Make COTS and Revise: the working revision's CAD files, and the reasons
    the part can't go ahead yet (checked out, modified, behind the vault...)."""
    ctx = ctx or PlanContext(repo)
    record_path = record_store.record_relpath(pn)
    cad = ctx.cad_index().get(pn, {}).get(record.revision, [])
    group = cad + [record_path]
    problems = []

    if record.status != required:
        problems.append(f"Its status is '{record.status}'. Only {required_label} parts can be {verb}.")
    if record.pending and not allow_pending:
        problems.append("It is waiting for sign-offs.")
    if record.draft and record.draft.get("id") != ctx.draft_ok:
        problems.append(draft_problem(record))
    if not cad and record.uses_cad:
        problems.append("There are no CAD files for it in the cad folder.")

    if fetch:   # look at the vault's current state without changing any of your files
        ctx.fetch()

    locks = ctx.locks()
    owners = sorted({locks[p.lower()][1] for p in group if p.lower() in locks})
    if owners:
        problems.append("It is checked out by " + ", ".join(owners) + ".")

    modified = ctx.modified()
    for f in cad:
        if f.lower() in modified:
            problems.append(f"{f} has changes that are not checked in.")
        # A file that is not downloaded is fine: releasing only changes the record (download on demand).

    if any(path in ctx.changed_in(repository.UNPUSHED) for path in group):
        problems.append("Some changes have not been uploaded yet.")
    if any(path in ctx.changed_in(repository.INCOMING) for path in group):
        problems.append("A newer version is in the vault. Run Get Latest first.")
    return cad, problems


def draft_problem(record):
    """Why a part in a rejected workflow can't go into anything else."""
    return (f"It is in a rejected workflow that {record.draft.get('requested_by') or 'someone'} is changing (a "
            "draft). Resubmit or withdraw it first.")


@converts_errors
def release_plan(repo, pn, fetch=True, allow_pending=False, ctx=None):
    """Work out what a release would freeze and whether anything blocks it.

    Show plan.files to the user for confirmation, and plan.problems if it isn't ok.
    """
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    ctx = ctx or PlanContext(repo)
    cad, problems = blockers(repo, pn, record, "released", fetch, allow_pending=allow_pending, ctx=ctx)
    if record.cots:
        problems.insert(0, "It is a COTS (purchased) part, which is never released.")
    problems.extend(toolbox_check.release_problems(repo, record, record.revision, cad))
    warnings = []
    rule = config.get_release_rule(repo)
    if rule != "off" and not record.cots:
        from litterbox.references import reference_queries
        found = reference_queries.release_warnings(repo, pn, ctx.records())
        if rule == "block":
            problems.extend(found)
        else:
            warnings = found
    return ReleasePlan(pn, record.name, cad, problems, warnings)


@converts_errors
def make_cots_plan(repo, pn, fetch=True, allow_pending=False, ctx=None):
    """Work out whether a part can be turned into a COTS part. Same checks as a release:
    nobody has it checked out, nothing is modified, and your copy is up to date."""
    repository.validate_repo(repo)
    pn = batch_core.as_pn(pn)
    record = record_store.load(repo, pn)
    cad, problems = blockers(repo, pn, record, "made COTS", fetch, allow_pending=allow_pending,
                              ctx=ctx or PlanContext(repo))
    if not record.uses_cad:
        problems.insert(0, "It is non-CAD: it has no CAD model. Release it instead.")
    if record.cots:
        problems.insert(0, "It is already a COTS part.")
    elif record.released_revision or record.revision != revision_letters.FIRST_REVISION:
        problems.insert(0, "It has been released or revised, so it is not an unmodified purchased part.")
    return ReleasePlan(pn, record.name, cad, problems)


def release_plans(repo, pns, allow_pending=False):
    """release_plan() for several parts, looking at the vault once. A part that can't be read gets a plan with
    that as its problem."""
    ctx, plans = PlanContext(repo), []
    for pn in batch_core.unique_pns(pns):
        try:
            plans.append(release_plan(repo, pn, allow_pending=allow_pending, ctx=ctx))
        except LitterboxError as e:
            plans.append(ReleasePlan(pn, "", [], [str(e)]))
    return plans


def make_cots_plans(repo, pns, allow_pending=False):
    """make_cots_plan() for several parts, looking at the vault once."""
    ctx, plans = PlanContext(repo), []
    for pn in batch_core.unique_pns(pns):
        try:
            plans.append(make_cots_plan(repo, pn, allow_pending=allow_pending, ctx=ctx))
        except LitterboxError as e:
            plans.append(ReleasePlan(pn, "", [], [str(e)]))
    return plans
