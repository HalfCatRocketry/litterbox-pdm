"""
workflow_tasks.py - "My tasks": the requests waiting on you, worked out from the parts list.
"""

from dataclasses import dataclass

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
    slots: list                     # [{'text', 'name', 'id', 'done'}]
    ready: bool                     # every sign-off is in on every part; waiting to be completed
    mine: bool                      # you asked for it
    reason: str = ""
    template_name: str = ""
    can_sign: bool = False
    can_reject: bool = False
    can_complete: bool = False
    can_withdraw: bool = False
    can_override: bool = False
    can_reassign: bool = False
    why_not_sign: str = ""

    @property
    def pns(self):
        return [p[0] for p in self.parts]

    @property
    def label(self):
        first = str(self.parts[0][0])
        return first if len(self.parts) == 1 else f"{first} +{len(self.parts) - 1} more"


def tasks_from_rows(rows, identity):
    """Everything waiting on a sign-off, from the part list's rows (PartStatus), one task per request. With no
    team member identity the tasks are listed, but nothing can be done to them."""
    me = identity.person if identity.state == team_identity.OK else None
    groups = {}
    for row in rows:
        pending = getattr(row, "pending", None)
        if not pending or "slots" not in pending:
            continue
        groups.setdefault(pending.get("id") or str(row.pn), []).append(row)
    tasks = []
    for batch_id, members in groups.items():
        first = members[0].pending
        pendings = [m.pending for m in members]
        done = [all(signoff_slots.slot_done(p, i) for p in pendings) for i in range(len(first["slots"]))]
        slots = [{"text": signoff_slots.slot_text(s), "name": s["name"], "id": s.get("id"), "done": done[i], "roles": list(s["roles"])}
                 for i, s in enumerate(first["slots"])]
        ready = all(done)
        names = [s["name"] for s, d in zip(first["slots"], done) if not d]
        label = workflow_templates.label_of(first.get("action"))
        summary = (f"{label} approved - ready to complete" if ready else
                   f"{label} pending {sum(done)}/{len(done)}: waiting on " + ", ".join(names))
        task = Task(batch_id, first.get("action", workflow_templates.RELEASE), [(m.pn, m.name, first.get("revision", "")) for m in members],
                    first.get("requested_by", ""), first.get("requested_at", ""), summary, slots, ready,
                    me is not None and first.get("requested_by_id") == me.id, first.get("reason", ""),
                    first.get("template_name", ""))
        if me is not None:
            task.can_sign = any(signoff_slots.open_slots(p, me.id) for p in pendings)
            if not task.can_sign:
                task.why_not_sign = signoff_slots.may_sign(first, me)[1]
            task.can_reject = any(signoff_slots.is_signer(p, me) for p in pendings) or signoff_slots.is_admin(me)
            task.can_complete = ready
            task.can_withdraw = task.mine or signoff_slots.is_admin(me)
            task.can_override = signoff_slots.is_admin(me)
            task.can_reassign = (task.mine or signoff_slots.is_admin(me)) and not ready
        tasks.append(task)
    tasks.sort(key=lambda t: (not (t.can_sign or (t.ready and t.mine)), t.requested_at))
    return tasks


def count_for_me(tasks):
    """How many tasks need you: sign-offs you can give, and your own approved requests waiting to be completed."""
    return sum(1 for t in tasks if t.can_sign or (t.ready and t.mine))
