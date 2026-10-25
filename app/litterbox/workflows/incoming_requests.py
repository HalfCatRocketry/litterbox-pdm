"""
incoming_requests.py - the requests the vault's server has that this copy hasn't got yet, so My Tasks and All
Workflows show them at a refresh, without Get Latest.

A refresh already fetches (git/remote.commits_behind). When this copy is behind, read() looks at the records the
server's newer commits changed: one git diff for which, one git grep for those with a request (pending or draft), and
one git show for each of those. Nothing in the copy changes. apply() puts what it found into the rows the task lists
are worked out from; a request there is marked `incoming`, and acting on it gets the latest first (the sign-off,
completion and so on then work on the copy as usual).
"""

import dataclasses
import fnmatch

import yaml

from litterbox import layout
from litterbox.git import repository
from litterbox.git import sparse
from litterbox.parts import part_status
from litterbox.records import record_model
from litterbox.util import fast_yaml

FOLDERS = (layout.LOG_DIR_NAME, layout.DOC_LOG_DIR_NAME)
REQUEST_LINE = "^(pending|draft):"          # a record with a request has one of these at the top level


def read(repo):
    """{number text: Record, or None when the server's record has no request now} for every record the server's
    newer commits changed. {} when there are none or it can't be told. Call it after a fetch, when the copy is
    behind. Records of hidden projects this copy leaves out stay out."""
    upstream = repository.quiet_output(repo, "rev-parse", "--verify", "@{upstream}").strip()
    if not upstream:
        return {}
    changed = [p for p in repository.quiet_output(repo, "diff", "--name-only", f"HEAD...{upstream}", "--",
                                                  *FOLDERS).splitlines() if p.endswith(".yaml")]
    left_out = sparse.excluded(repo)
    changed = [p for p in changed if not any(fnmatch.fnmatchcase("/" + p, pattern) for pattern in left_out)]
    if not changed:
        return {}
    # git grep finds nothing with an error too, but the server's commit was just read, so that means no requests
    found = repository.quiet_output(repo, "grep", "-l", "-E", REQUEST_LINE, upstream, "--", *FOLDERS)
    with_request = {line.split(":", 1)[1] for line in found.splitlines() if ":" in line}
    records = {}
    for path in changed:
        number = path.rsplit("/", 1)[-1][:-len(".yaml")]
        records[number] = _record(repo, upstream, path) if path in with_request else None
    return {number: record for number, record in records.items() if record is not False}


def _record(repo, upstream, path):
    """The server's record at `path`, or False if it can't be read (that record is then left as this copy has it)."""
    try:
        return record_model.Record.from_dict(fast_yaml.safe_load(
            repository.quiet_output(repo, "show", f"{upstream}:{path}")))
    except (yaml.YAMLError, record_model.RegistryError, AttributeError, TypeError, ValueError):
        return False


def apply(rows, incoming):
    """`rows` (PartStatus) with the server's requests from read(): a row whose record the server changed takes its
    request (and name), and a record new on the server gets a row of its own, for the task lists only."""
    if not incoming:
        return list(rows)
    result, seen = [], set()
    for row in rows:
        number = str(row.pn)
        if number in incoming:
            seen.add(number)
            record = incoming[number]
            row = dataclasses.replace(row, pending=dict(record.pending or {}) if record else {},
                                      draft=dict(record.draft or {}) if record else {},
                                      name=record.name if record else row.name, incoming=True)
        result.append(row)
    for number, record in incoming.items():
        if number not in seen and record is not None and (record.pending or record.draft):
            result.append(part_status.PartStatus(
                record.pn, record.name, record.status, "", "pending", revision=record.revision,
                released_revision=record.released_revision, pending=dict(record.pending or {}),
                draft=dict(record.draft or {}), project=record.project, doc_type=record.doc_type, incoming=True))
    return result
