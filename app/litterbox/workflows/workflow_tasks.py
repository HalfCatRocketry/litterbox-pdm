"""
workflow_tasks.py - the Workflows screen's lists, worked out from the parts list: My Tasks (the requests you are
named to sign or asked for, and your rejected requests waiting to be changed) and All Workflows (every request, for
Admins and superusers).
"""

from dataclasses import dataclass, field

from litterbox.team import team_identity
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_templates


@dataclass
class Task:
    """One request (a batch of parts) as My Tasks shows it."""
    id: str
    action: str
    parts: list                     # [(PN, name, revision)]
    requested_by: str
    requested_at: str
    summary: str
    slots: list                     # [{'text', 'name', 'id', 'done', 'roles', 'extra'}]
    ready: bool                     # every sign-off is in on every part; waiting to be completed
    mine: bool                      # you asked for it
    reason: str = ""
    template_name: str = ""
    eco: str = ""                   # its engineering change order (ECO-0001), if the workflow asked for one
    can_sign: bool = False
    can_reject: bool = False
    can_complete: bool = False
    can_withdraw: bool = False
    can_override: bool = False      # an Admin: Override Approve and Override Reject
    can_reassign: bool = False
    why_not_sign: str = ""
    involved: bool = False          # you are named to sign it, or you asked for it
    superuser_slots: list = field(default_factory=list)    # sign-offs you may give as a superuser (indices)
    my_slots: list = field(default_factory=list)           # sign-offs named for you, not given yet (indices)
    changes: dict = field(default_factory=dict)            # {part number text: {"changed", "disposition"}}
    earlier: dict = field(default_factory=dict)            # {part number text: the revision released before}
    draft: bool = False             # rejected, and waiting for whoever asked to change it (workflow_drafts.py)
    rejected: dict = field(default_factory=dict)           # who rejected it, when and why ({"by", "at", "comment"})
    document: str = ""              # the document a Remove document link request takes off
    requested_by_id: str = ""

    @property
    def pns(self):
        return [p[0] for p in self.parts]

    @property
    def label(self):
        first = str(self.parts[0][0])
        return first if len(self.parts) == 1 else f"{first} +{len(self.parts) - 1} more"


def can_see_all(identity):
    """True if this person gets the All Workflows tab: an Admin (or the Owner), or someone with a superuser role."""
    me = identity.person if identity.state == team_identity.OK else None
    return me is not None and (signoff_slots.is_admin(me) or
                               (identity.directory is not None and identity.directory.is_superuser(me)))


def _group(rows, key):
    groups = {}
    for row in rows:
        request = getattr(row, key, None)
        if not request or "slots" not in request:
            continue
        groups.setdefault(request.get("id") or str(row.pn), []).append(row)
    return groups


def _task(batch_id, members, key, me):
    first = getattr(members[0], key)
    requests = [getattr(m, key) for m in members]
    draft = key == "draft"
    done = [not draft and all(signoff_slots.slot_done(p, i) for p in requests) for i in range(len(first["slots"]))]
    slots = [{"text": signoff_slots.slot_text(s), "name": s["name"], "id": s.get("id"), "done": done[i],
              "roles": list(s["roles"]), "extra": bool(s.get("extra"))} for i, s in enumerate(first["slots"])]
    label = workflow_templates.label_of(first.get("action"))
    rejected = first.get("rejected") or {}
    if draft:
        summary = f"{label} rejected by {rejected.get('by', '')}: needs changes"
    elif all(done):
        summary = f"{label} approved - ready to complete"
    else:
        names = [s["name"] for s, d in zip(first["slots"], done) if not d]
        summary = f"{label} pending {sum(done)}/{len(done)}: waiting on " + ", ".join(names)
    return Task(batch_id, first.get("action", workflow_templates.RELEASE),
                [(m.pn, m.name, getattr(m, key).get("revision", "")) for m in members],
                first.get("requested_by", ""), first.get("requested_at", ""), summary, slots, not draft and all(done),
                me is not None and first.get("requested_by_id") == me.id, first.get("reason", ""),
                first.get("template_name", ""), first.get("eco", ""),
                changes={str(m.pn): dict(getattr(m, key).get("change") or {}) for m in members},
                earlier={str(m.pn): _earlier(m, getattr(m, key)) for m in members},
                draft=draft, rejected=dict(rejected), document=first.get("document", ""),
                requested_by_id=first.get("requested_by_id", ""))


def _earlier(row, request):
    released = getattr(row, "released_revision", "")
    return released if released and released != request.get("revision") else ""


def tasks_from_rows(rows, identity, everything=False):
    """The requests waiting on a sign-off, from the part list's rows (PartStatus), one task per request: only the
    ones you are involved in (named to sign, or asked for), or with everything=True all of them. A rejected request
    (a draft) is only the business of whoever asked (and, in All Workflows, of everyone who sees it). With no team
    member identity nothing can be done to them."""
    me = identity.person if identity.state == team_identity.OK else None
    directory = getattr(identity, "directory", None)
    tasks = []
    for key in ("pending", "draft"):
        for batch_id, members in _group(rows, key).items():
            task = _task(batch_id, members, key, me)
            requests = [getattr(m, key) for m in members]
            who = getattr(identity, "person", None)
            task.involved = who is not None and (task.requested_by_id == who.id or (not task.draft and any(
                signoff_slots.is_signer(p, who) for p in requests)))
            if not (everything or task.involved):
                continue
            if me is not None:
                _abilities(task, requests, me, directory)
            tasks.append(task)
    tasks.sort(key=lambda t: (not needs_me(t), t.requested_at))
    return tasks


def _abilities(task, requests, me, directory):
    admin = signoff_slots.is_admin(me)
    task.can_withdraw = task.mine or admin
    if task.draft:
        task.why_not_sign = "It was rejected and is waiting for whoever asked to change it."
        return
    task.my_slots = sorted(set().union(*(signoff_slots.open_slots(p, me.id) for p in requests)))
    task.can_sign = bool(task.my_slots)
    task.superuser_slots = sorted(set().union(*(signoff_slots.superuser_slots(p, me, directory) for p in requests)))
    if not task.can_sign:
        task.why_not_sign = signoff_slots.may_sign(requests[0], me)[1]
    task.can_reject = any(signoff_slots.is_signer(p, me) for p in requests) or admin
    task.can_complete = task.ready
    task.can_override = admin
    task.can_reassign = (task.mine or admin) and not task.ready


def needs_me(task):
    """True if the task waits on you: a sign-off you can give, your own approved request waiting to be completed,
    or your own rejected request waiting to be changed."""
    return task.can_sign or (task.mine and (task.ready or task.draft))


def count_for_me(tasks):
    """How many tasks need you (needs_me)."""
    return sum(1 for t in tasks if needs_me(t))
