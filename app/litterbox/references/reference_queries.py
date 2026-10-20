"""
reference_queries.py - what a part uses, where it is used, which uses are out of date, and the warnings
shown before releasing an assembly (see the vault's release_rule).
"""

from litterbox.core import revision_letters
from litterbox.parts import batch_core
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.references import reference_model


def _parent_revision_status(record, revision):
    if revision == record.revision:
        return record.status
    return record_model.STATUS_RELEASED         # earlier revisions are always released


def _use(records, parent_record, revision, stem):
    parts = reference_model.split_stem(stem)
    if parts is None:
        return None
    child, child_revision = parts
    child_record = records.get(child)
    state, latest = reference_model.classify(child_record, child_revision)
    status = _parent_revision_status(parent_record, revision)
    editable = (revision == parent_record.revision and status == record_model.STATUS_IN_WORK
                and not parent_record.cots)
    return reference_model.Use(parent_record.pn, revision, child, child_revision, state, latest,
               parent_record.name, child_record.name if child_record else "", status, editable)


def uses(repo, pn, revision=None, records=None):
    """What the part's assembly (at `revision`, default the working one) uses: a list of Use."""
    records = records if records is not None else reference_model.LazyRecords(repo)
    pn = batch_core.as_pn(pn)
    record = records.get(pn)
    if record is None:
        raise reference_model.ReferencesError(f"There is no record for {pn}.")
    revision = revision or record.revision
    found = [_use(records, record, revision, stem) for stem in record.references.get(revision, [])]
    return sorted((u for u in found if u), key=lambda u: (str(u.child), u.child_revision))


def where_used(repo, pn, records=None):
    """Every assembly revision that uses this part (any revision of it): a list of Use."""
    records = records if records is not None else reference_model.load_records(repo)
    pn = batch_core.as_pn(pn)
    found = []
    for parent_record in records.values():
        for revision, stems in parent_record.references.items():
            for stem in stems:
                parts = reference_model.split_stem(stem)
                if parts and parts[0] == pn:
                    found.append(_use(records, parent_record, revision, stem))
    return sorted((u for u in found if u),
                  key=lambda u: (str(u.parent), revision_letters.revision_number(u.parent_revision), u.child_revision))


def stale_uses(repo, pn, records=None):
    """The references of the part's working revision that are not OK."""
    return [u for u in uses(repo, pn, None, records) if u.state != reference_model.OK]


def stale_everywhere(repo, records=None):
    """Every reference, in every assembly still in work, that Litterbox could point at a newer revision."""
    records = records if records is not None else reference_model.load_records(repo)
    found = []
    for record in records.values():
        if record.status == record_model.STATUS_IN_WORK and not record.cots:
            found.extend(u for u in uses(repo, record.pn, None, records) if u.replaceable)
    return found


def needs_update(repo, record):
    """Revisions of this part whose list of parts used is missing or out of date."""
    return [rev for rev, files in record_files.cad_index(repo).get(record.pn, {}).items()
            if record_lifecycle.references_need_update(record, rev, files)]


def bom_needs_update(repo, record):
    """Revisions of this part whose BOM quantities are missing or out of date."""
    return [rev for rev, files in record_files.cad_index(repo).get(record.pn, {}).items()
            if record_lifecycle.bom_needs_update(record, rev, files)]


def outdated_parts(repo, records=None):
    """Every part in the vault whose list of parts used is missing or out of date."""
    records = records if records is not None else reference_model.load_records(repo)
    index = record_files.cad_index(repo)
    return sorted(pn for pn, record in records.items()
                  if any(record_lifecycle.references_need_update(record, rev, files)
                         for rev, files in index.get(pn, {}).items()))


def release_warnings(repo, pn, records=None):
    """Sentences about references that make a release a bad idea (empty if none)."""
    problems = []
    record = (records or reference_model.LazyRecords(repo)).get(batch_core.as_pn(pn))
    if record is not None and needs_update(repo, record):
        problems.append("The list of parts it uses is out of date, so these checks may be wrong. "
                        "Use References... then Update references.")
    for use in uses(repo, pn, None, records):
        if use.state == reference_model.OK:
            continue
        what = f"{use.child} Rev {use.child_revision}"
        if use.state == reference_model.STALE:
            problems.append(f"It uses {what}, but Rev {use.latest_released} has been released since.")
        elif use.state == reference_model.UNRELEASED:
            problems.append(f"It uses {what}, which has not been released.")
        elif use.state == reference_model.CANCELLED:
            problems.append(f"It uses {what}, whose revision was cancelled.")
        elif use.state == reference_model.VOID:
            problems.append(f"It uses {what}, which was voided.")
        else:
            problems.append(f"It uses {what}, which has no record in the vault.")
    return problems
