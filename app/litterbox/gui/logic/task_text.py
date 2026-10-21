"""
task_text.py - the Workflows screen (My Tasks and All Workflows) and workflow requests: the task table, a task's
details, which buttons work, the request confirmation, and the people that can be picked for a slot.
"""

from litterbox.gui.logic import history_text
from litterbox.team import team_identity
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates


def request_confirm_text(action, parts, template, slots, reason="", warnings=(), eco=None):
    """The question asked at the end of the Workflow window, before the request is made. `eco` is the ECO's
    {"name", "description"} when the workflow requires one."""
    label = workflow_templates.label_of(action)
    listing = "\n".join(f"  {pn}  {name}".rstrip() for pn, name in parts)
    signers = "\n".join(f"  {signoff_slots.slot_text(s)}: {s['name']}" for s in slots)
    text = (f"Start the {label} workflow ({template.name}) on:\n\n{listing}\n\nThese people will be asked to "
            f"sign off:\n{signers}\n\n")
    if reason:
        text += f"Reason: {reason}\n\n"
    if eco is not None:
        text += f"An engineering change order (ECO) will be made: {eco['name']}\n\n"
    text += ("While it waits, nobody can check these parts out. You can withdraw the request until it is done."
             + (" It happens as soon as the last person signs." if action in workflow_templates.AUTO_COMPLETE else
                " When everyone has signed, press the button again to finish it."))
    if warnings:
        text += "\n\nNOTE:\n" + "\n".join("- " + w for w in warnings)
    return text


TASK_COLUMNS = (("part", "Parts", 150), ("name", "Name", 200), ("action", "Action", 90), ("by", "Asked by", 120),
                ("when", "Asked", 120), ("status", "Status", 330))


def tasks_table(tasks, local=True):
    """Rows of (iid, values) for the My Tasks window (one row per request)."""
    rows = []
    for t in tasks:
        name = t.parts[0][1] if len(t.parts) == 1 else f"{len(t.parts)} parts"
        rows.append((t.id, (t.label, name, workflow_templates.label_of(t.action), t.requested_by,
                            history_text.to_display_time(t.requested_at, local), t.summary)))
    return rows


def tasks_summary(tasks, everything=False):
    """The line above a Workflows table."""
    if not tasks:
        return ("Nothing is waiting for sign-off." if everything else
                "Nothing is waiting on you.") + " Press Get Latest to check for new requests."
    count = f"{len(tasks)} request{'s' if len(tasks) != 1 else ''}"
    if everything:
        return f"{count} waiting. Press Get Latest to see new ones."
    mine = workflow_tasks.count_for_me(tasks)
    return f"{count} you sign or asked for; {mine} need{'s' if mine == 1 else ''} you. Press Get Latest to see new ones."


def button_states(task):
    """{button key: usable} for the selected task (None: nothing selected)."""
    if task is None:
        return dict.fromkeys(("sign", "reject", "complete", "withdraw", "reassign", "override", "override_reject",
                              "superuser"), False)
    return {"sign": task.can_sign, "reject": task.can_reject, "complete": task.can_complete,
            "withdraw": task.can_withdraw, "reassign": task.can_reassign, "override": task.can_override,
            "override_reject": task.can_override, "superuser": bool(task.superuser_slots)}


def all_workflows_buttons(identity):
    """The keys of the All Workflows buttons this person gets: Approve as superuser for a superuser, Override
    Approve and Override Reject for an Admin, and the rest for both."""
    shown = {"complete", "reassign", "withdraw"}
    me = identity.person if identity.state == team_identity.OK else None
    if me is None:
        return shown
    if identity.directory is not None and identity.directory.is_superuser(me):
        shown.add("superuser")
    if signoff_slots.is_admin(me):
        shown |= {"override", "override_reject"}
    return shown


def superuser_slot_text(slot):
    """A tick box of the Approve as superuser window: 'Quality (named: Bea)'."""
    return f"{slot['text']} (named: {slot['name']})"


def task_detail(task):
    """Lines under the My Tasks table: who has signed and who is still to."""
    lines = [f"{'✓' if s['done'] else '…'} {s['text']}: {s['name']}" + ("" if s["done"] else " (waiting)")
             for s in task.slots]
    head = ", ".join(str(p[0]) for p in task.parts)
    text = f"{head}\n" + "   ".join(lines)
    if task.eco:
        text += f"\nECO: {task.eco}"
    if task.reason:
        text += f"\nReason: {task.reason}"
    return text


def signoff_result_text(result, label="request"):
    """(text, warn) shown after signing: '' when it all went to plan."""
    if not result.errors:
        return "", False
    lines = "\n".join(f"{pn}: {why}" for pn, why in result.errors.items())
    return (f"Your sign-off is saved where it could be, but not everything went through:\n\n{lines}\n\n"
            "Whoever asked (or anyone) can finish it from Workflows or with the action's button.", True)


def person_labels(people_list):
    """[(label, id)] for a drop-down of people; adds the id when two people share a name."""
    names = [p.name for p in people_list]
    return [(p.name if names.count(p.name) == 1 else f"{p.name} ({p.id})", p.id) for p in people_list]


def row_choices(directory, roles, requester_id=None, requester_may_sign=True):
    """[(label, id)] of the people who can fill a sign-off with any of these roles."""
    found = workflow_editing.eligible(directory, roles)
    if not requester_may_sign:
        found = [p for p in found if p.id != requester_id]
    return person_labels(found)
