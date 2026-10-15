"""
workflow_ecos.py - the ECO side of a workflow: opening one with a request, and closing it when the request ends.

Ending a request (completing, overriding, rejecting, withdrawing) edits its parts' records through the batch core;
an EcoCloser notes each part's request as the edit sees it, and afterwards (in the same commit) closes every ECO
whose parts are all done. See change_orders/.
"""

import copy

from litterbox.change_orders import eco_lifecycle
from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store


class EcoCloser:
    """Pass note() each request an edit ends, and finish as the batch core's finish hook."""

    def __init__(self, repo, status, comment=""):
        self.repo, self.status, self.comment = repo, status, comment
        self.requests = {}              # ECO number -> the request as it was

    def note(self, pending):
        if pending and pending.get("eco"):
            self.requests.setdefault(pending["eco"], copy.deepcopy(pending))

    def finish(self, user, _edited):
        paths = []
        for number, pending in self.requests.items():
            path = eco_lifecycle.close_if_done(self.repo, number, self.status, user, pending, self.comment)
            if path:
                paths.append(path)
        return paths


def eco_fields(template, eco):
    """(name, description) checked, if the template requires an ECO; None if it doesn't. Raises EcoError."""
    if not template.require_eco:
        return None
    eco = eco or {}
    return eco_model.clean_name(eco.get("name")), eco_model.clean_description(eco.get("description"))


def opener(repo, fields, action, template_name, request_id, parts):
    """A prepare hook for the batch core that writes the request's ECO, numbered after the pull. `fields` is
    eco_fields(); `parts()` gives [(PN, revision)] (called after the pull too). Returns (hook, holder):
    holder["eco"] is the new ECO's number once the hook has run."""
    holder = {}

    def prepare(user):
        if fields is None:
            return []
        eco = eco_lifecycle.open_eco(repo, fields[0], fields[1], action, template_name, request_id, parts(), user)
        holder["eco"] = eco.number
        return [eco_store.relpath(eco.number)]
    return prepare, holder
