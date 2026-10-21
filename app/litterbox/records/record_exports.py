"""
record_exports.py - the STEP and PDF files Litterbox made for a part's revisions, as its record keeps them.

    exports:
      A:
        wanted: true                  set at release: the released revision should get its STEP and PDF made
        step: {file: cad/HCR-00042-001_A.STEP, by: Alex, at: ..., solidworks: '32.1.0',
               from: {cad/HCR-00042-001_A.SLDPRT: <sha256>}}
        pdf: {...}                    the same, made from the drawing

A release asks for both again (`wanted`, set by record_lifecycle.mark_released), so a release always gets files
made from the files it froze. Once every file the revision can have has been made, `wanted` goes. A released
revision still `wanted` is what the window shows as "STEP/PDF needs updating". Parts released before Litterbox made these files have no entry and are never
flagged. Which kinds a revision can have depends on its files (a PDF needs a drawing): the caller says.
"""

from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.util import person_name


STEP, PDF = "step", "pdf"
KINDS = (STEP, PDF)
LABEL = {STEP: "STEP", PDF: "PDF"}


def is_flagged(record):
    """True when the released working revision still needs its STEP and/or PDF made."""
    return (record.status == record_model.STATUS_RELEASED and record.revision == record.released_revision
            and bool(record.exports.get(record.revision, {}).get("wanted")))


def needed(record, possible):
    """The kinds the released working revision still needs, out of the kinds its files allow (`possible`).
    Empty when it isn't flagged."""
    if not is_flagged(record):
        return []
    made = record.exports.get(record.revision, {})
    return [kind for kind in KINDS if kind in possible and kind not in made]


def record_made(record, by, revision, made, possible, forced=False):
    """Note files Litterbox made for a revision. `made` is {kind: {"file": ..., "from": {file: sha256},
    "solidworks": version}}; `possible` the kinds the revision's files allow. The revision's flag is cleared once
    it has all of them. Returns the history entry."""
    entry = record.exports.setdefault(revision, {})
    at = record_model.now_utc()
    for kind in KINDS:
        if kind not in made:
            continue
        details = made[kind]
        entry[kind] = {"file": details["file"], "by": str(by).strip(),
                       **({"by_id": person_name.id_of(by)} if person_name.id_of(by) else {}), "at": at,
                       **({"solidworks": details["solidworks"]} if details.get("solidworks") else {}),
                       "from": dict(details.get("from") or {})}
    if entry.get("wanted") and all(kind in entry for kind in possible):
        entry.pop("wanted")
    return record_lifecycle.add_event(record, record_model.EVENT_FILES_MADE, by, revision=revision,
                                      files=[made[kind]["file"] for kind in KINDS if kind in made],
                                      forced=True if forced else None)
