"""
eco_lifecycle.py - opening an ECO with its workflow request, and closing it when the request ends.

    open      written in the same commit as the request (workflow_request.request): status "open"
    released  the workflow completed (the last sign-off, Complete, or an Admin's override)
    rejected  a signer rejected the request. Since 0.5.4 a rejected request becomes a draft that is changed and
              resubmitted, so its ECO stays open: the rejection and the resubmission go in its history (note(),
              resubmit()). Older ECOs may still be closed as rejected.
    withdrawn whoever asked withdrew it (or its draft)

These run inside the batch core's commit (parts/batch_core.edit_records), while the locks of the ECO's parts are
held: those locks are what stop two people changing the same ECO at once. A closed ECO is never changed again.
"""

from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store
from litterbox.core import part_number
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.util import person_name

EVENT = {eco_model.RELEASED: "released", eco_model.REJECTED: "rejected", eco_model.WITHDRAWN: "withdrawn"}


def part_entries(parts):
    """An ECO's `parts` from [(PN, revision)] or [(PN, revision, change)], where change is what the request says
    changed and the disposition of the earlier revision's parts (records/record_changes.py)."""
    entries = []
    for item in parts:
        pn, rev, change = (tuple(item) + ({},))[:3]
        entries.append({"pn": str(pn), "revision": rev, **{k: v for k, v in (change or {}).items() if v}})
    return entries


def open_eco(repo, name, description, action, template_name, request_id, parts, user):
    """Write a new ECO for a request and return it. `parts` is as part_entries() takes. Its number is the next free
    one in your copy, so call this after pulling."""
    name, description = eco_model.clean_name(name), eco_model.clean_description(description)
    eco = eco_model.Eco(eco_store.next_number(repo), name, description, eco_model.OPEN, action, template_name,
                        request_id, part_entries(parts), str(user),
                        record_model.now_utc(), requested_by_id=person_name.id_of(user))
    eco.history.append(person_name.stamp({"event": "opened"}, "by", user) | {"at": eco.requested_at})
    eco_store.save(repo, eco)
    return eco


def _open_one(repo, number):
    eco = eco_store.load(repo, number)
    if eco.closed:
        raise eco_model.EcoError(f"{number} is {eco.status} and can't be changed.")
    return eco


def _stamp(eco, event, user, comment=""):
    entry = person_name.stamp({"event": event}, "by", user) | {"at": record_model.now_utc()}
    if comment:
        entry["comment"] = comment
    eco.history.append(entry)


def note(repo, number, event, user, comment=""):
    """Add an event to an open ECO's history without closing it ('rejected': its request became a draft).
    Returns the ECO file's path."""
    eco = _open_one(repo, number)
    _stamp(eco, event, user, comment)
    return eco_store.save(repo, eco)


def resubmit(repo, number, name, description, template_name, parts, user):
    """A draft's request asked again: the same ECO, with the title, description, workflow and parts it has now.
    Returns the ECO file's path."""
    eco = _open_one(repo, number)
    eco.name, eco.description = eco_model.clean_name(name), eco_model.clean_description(description)
    eco.template_name, eco.parts = template_name, part_entries(parts)
    _stamp(eco, "resubmitted", user)
    return eco_store.save(repo, eco)


def close(repo, number, status, user, comment=""):
    """Close an open ECO whatever its parts are doing (a resubmitted draft whose parts are all at Rev A no longer
    needs one). Returns the ECO file's path."""
    eco = _open_one(repo, number)
    eco.status = status
    _stamp(eco, EVENT[status], user, comment)
    return eco_store.save(repo, eco)


def close_if_done(repo, number, status, user, pending=None, comment=""):
    """Close the ECO if none of its parts still waits on its request. `pending` is the request as it was (its
    sign-offs are copied). Returns the ECO file's path if it was changed, else None."""
    eco = _open_one(repo, number)
    for part in eco.parts:
        try:
            record = record_store.load(repo, part_number.parse(part["pn"]))
        except record_model.RegistryError:
            continue
        if any(waiting and waiting.get("id") == eco.request_id for waiting in (record.pending, record.draft)):
            return None                 # part of the request is still waiting (or being changed)
    eco.status = status
    if pending:
        eco.signoffs = [dict(s) for s in pending.get("signoffs", [])]
    _stamp(eco, EVENT[status], user, comment)
    return eco_store.save(repo, eco)
