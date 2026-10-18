"""
signoff_slots.py - the sign-off slots of a pending request: who is named for each, who has signed, who
the request is still waiting on, and whether a person may sign.
"""

from litterbox.team import team_model
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_templates


def slot_done(pending, index):
    return any(e.get("slot") == index for e in pending.get("signoffs", []))


def slot_text(slot):
    return " or ".join(slot["roles"]) + (" (extra)" if slot.get("extra") else "")


def is_complete(pending):
    return all(slot_done(pending, i) for i in range(len(pending["slots"])))


def signed_count(pending):
    return sum(1 for i in range(len(pending["slots"])) if slot_done(pending, i))


def describe_pending(pending):
    """Short text for the part list: 'Release pending 1/3: Bea, Alex'."""
    label = workflow_templates.label_of(pending.get("action"))
    if is_complete(pending):
        return f"{label} approved - ready to complete"
    names = [s["name"] for i, s in enumerate(pending["slots"]) if not slot_done(pending, i)]
    return f"{label} pending {signed_count(pending)}/{len(pending['slots'])}: waiting on " + ", ".join(names)


def waiting_on(pending):
    """['Quality (Bea)', ...] for the sign-offs not given yet."""
    return [f"{slot_text(s)} ({s['name']})" for i, s in enumerate(pending["slots"]) if not slot_done(pending, i)]


def open_slots(pending, person_id):
    """Indices of the sign-offs named for this person that they haven't given."""
    return [i for i, s in enumerate(pending["slots"]) if s.get("id") == person_id and not slot_done(pending, i)]


def is_admin(person):
    return person.access in (team_model.OWNER, team_model.ADMIN)


def is_signer(pending, person):
    return any(s.get("id") == person.id for s in pending["slots"])


def may_sign(pending, person):
    """(True, '') or (False, why not) for this person signing this request."""
    if open_slots(pending, person.id):
        return True, ""
    if is_complete(pending):
        return False, "Everyone needed has already signed."
    if is_signer(pending, person):
        return False, "You have already signed everything that was asked of you."
    return False, "You are not one of the people named to sign this."


def build_slots(template, directory, requester_id, assignments, extras=()):
    """The `slots` for a request: one per template row (the person named in `assignments`, in order) and one
    per extra (role, person id). Raises WorkflowError for anything the template doesn't allow."""
    if len(assignments) != len(template.rows):
        raise workflow_templates.WorkflowError("Choose a person for every sign-off.")
    slots = []
    for number, (row, pid) in enumerate(zip(template.rows, assignments), 1):
        slots.append(make_slot(directory, row.roles, pid, f"sign-off {number} ({row.text()})", False))
    for role, pid in extras:
        roles = [role] if isinstance(role, str) else list(role)
        match = [next((r for r in directory.roles if r.lower() == x.lower()), None) for x in roles]
        if not roles or None in match:
            raise workflow_templates.WorkflowError("An extra sign-off needs one of this org's roles.")
        slots.append(make_slot(directory, match, pid, f"the extra {' or '.join(match)} sign-off", True))
    ids = [s["id"] for s in slots]
    if not template.allow_same_person and len(set(ids)) != len(ids):
        raise workflow_templates.WorkflowError(f"The {template.name} workflow doesn't let one person fill more than one sign-off. "
                            "Choose different people.")
    if not template.requester_may_sign and requester_id in ids:
        raise workflow_templates.WorkflowError(f"The {template.name} workflow doesn't let you sign your own request. Choose someone "
                            "else for the sign-off.")
    return slots


def make_slot(directory, roles, person_id, where, extra):
    person = directory.get(person_id) if person_id else None
    if person is None:
        raise workflow_templates.WorkflowError(f"Choose a person for {where}.")
    if not workflow_editing.person_can_fill(person, roles):
        raise workflow_templates.WorkflowError(f"{person.name} is not active with the role needed for {where}.")
    return {"roles": list(roles), "id": person.id, "name": person.name, **({"extra": True} if extra else {})}
