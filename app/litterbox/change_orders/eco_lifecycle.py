"""
eco_lifecycle.py - opening an ECO with its workflow request, and closing it when the request ends.

    open      written in the same commit as the request (workflow_request.request): status "open"
    released  the workflow completed (the last sign-off, Complete, or an Admin's override)
    rejected  a signer rejected the request
    withdrawn whoever asked withdrew it

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


def open_eco(repo, name, description, action, template_name, request_id, parts, user):
    """Write a new ECO for a request and return it. `parts` is [(PN, revision)]. Its number is the next free one
    in your copy, so call this after pulling."""
    name, description = eco_model.clean_name(name), eco_model.clean_description(description)
    eco = eco_model.Eco(eco_store.next_number(repo), name, description, eco_model.OPEN, action, template_name,
                        request_id, [{"pn": str(pn), "revision": rev} for pn, rev in parts], str(user),
                        record_model.now_utc(), requested_by_id=person_name.id_of(user))
    eco.history.append(person_name.stamp({"event": "opened"}, "by", user) | {"at": eco.requested_at})
    eco_store.save(repo, eco)
    return eco


def close_if_done(repo, number, status, user, pending=None, comment=""):
    """Close the ECO if none of its parts still waits on its request. `pending` is the request as it was (its
    sign-offs are copied). Returns the ECO file's path if it was changed, else None."""
    eco = eco_store.load(repo, number)
    if eco.closed:
        raise eco_model.EcoError(f"{number} is {eco.status} and can't be changed.")
    for part in eco.parts:
        try:
            record = record_store.load(repo, part_number.parse(part["pn"]))
        except record_model.RegistryError:
            continue
        if record.pending and record.pending.get("id") == eco.request_id:
            return None                 # part of the request is still waiting
    eco.status = status
    if pending:
        eco.signoffs = [dict(s) for s in pending.get("signoffs", [])]
    entry = person_name.stamp({"event": EVENT[status]}, "by", user) | {"at": record_model.now_utc()}
    if comment:
        entry["comment"] = comment
    eco.history.append(entry)
    return eco_store.save(repo, eco)
