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
from litterbox.records import record_changes
from litterbox.workflows import workflow_templates


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


def eco_needed(template, action, revisions):
    """True if a request needs an ECO: its template requires one, unless it is a release whose parts are all at
    Rev A (a first release changes nothing, so there is no change order). `revisions` are the parts' working
    revisions."""
    if not template.require_eco:
        return False
    if workflow_templates.base_action(action) == workflow_templates.RELEASE:
        return not all(record_changes.first_release(rev) for rev in revisions)
    return True


def eco_fields(template, eco, needed=None):
    """(title, description) checked, if the request needs an ECO (`needed`, default: if the template requires
    one); None if it doesn't. Raises EcoError."""
    if not (template.require_eco if needed is None else needed):
        return None
    eco = eco or {}
    return eco_model.clean_name(eco.get("name")), eco_model.clean_description(eco.get("description"))


def opener(repo, fields, action, template_name, request_id, parts, existing=None):
    """A prepare hook for the batch core that writes the request's ECO, numbered after the pull. `fields` is
    eco_fields(); `parts()` gives [(PN, revision, change)] (called after the pull too). `existing` is the ECO of a
    draft being resubmitted: it carries on (or is withdrawn, if the request no longer needs one). Returns (hook,
    holder): holder["eco"] is the ECO's number once the hook has run, and holder["new"] is True for a new one."""
    holder = {}

    def prepare(user):
        if fields is None:
            if existing:
                return [eco_lifecycle.close(repo, existing, eco_model.WITHDRAWN, user,
                                            "No longer needed: every part is at its first release (Rev A).")]
            return []
        if existing:
            holder["eco"] = existing
            return [eco_lifecycle.resubmit(repo, existing, fields[0], fields[1], template_name, parts(), user)]
        eco = eco_lifecycle.open_eco(repo, fields[0], fields[1], action, template_name, request_id, parts(), user)
        holder["eco"], holder["new"] = eco.number, True
        return [eco_store.relpath(eco.number)]
    return prepare, holder


class EcoNoter:
    """A finish hook that adds an event to each noted request's ECO without closing it (a rejection)."""

    def __init__(self, repo, event, comment=""):
        self.repo, self.event, self.comment = repo, event, comment
        self.numbers = set()

    def note(self, pending):
        if pending and pending.get("eco"):
            self.numbers.add(pending["eco"])

    def finish(self, user, _edited):
        return [eco_lifecycle.note(self.repo, number, self.event, user, self.comment) for number in sorted(self.numbers)]
