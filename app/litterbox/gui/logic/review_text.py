"""
review_text.py - the Review window of My Tasks: what each sign-off row says, which of the Approve, Reject and
Reassign buttons work as you hand your sign-offs to other people, and the questions it asks.

Your sign-offs handed over in the window are only kept when you press a button at the bottom:
    Approve    hands those over, then approves the sign-offs you kept (needs at least one kept)
    Reject     rejects the whole request (needs at least one kept, and a comment); the hand-overs are dropped
    Reassign   hands them over and signs nothing (only once you have handed over every one)
"""

from litterbox.gui.logic import history_text
from litterbox.workflows import workflow_templates


def kept(my_slots, handed):
    """Your sign-offs (indices) not handed to someone else."""
    return [i for i in my_slots if i not in handed]


def buttons(my_slots, handed):
    """{"approve", "reject", "reassign"}: usable or not."""
    left = kept(my_slots, handed)
    return {"approve": bool(left), "reject": bool(left), "reassign": bool(my_slots) and not left}


def slot_status(slot, index, my_slots, handed_names):
    """What a sign-off row says beside its role: who, and how it stands. `handed_names` is {index: name} of yours
    handed over in this window."""
    if index in handed_names:
        return f"{slot['name']} → {handed_names[index]} (when you press Approve or Reassign)"
    if slot["done"]:
        return f"✓ {slot['name']} (signed)"
    if index in my_slots:
        return f"{slot['name']} (you, waiting)"
    return f"{slot['name']} (waiting)"


def summary_lines(task, local=True):
    """[(label, text)] above the sign-offs: the workflow, who asked and when, and the reason."""
    label = workflow_templates.label_of(task.action)
    lines = [("Workflow", f"{label} {task.template_name}".strip()),
             ("Asked by", f"{task.requested_by} on {history_text.to_display_time(task.requested_at, local)}")]
    if task.reason:
        lines.append(("Reason", task.reason))
    if task.document:
        lines.append(("Document", task.document))
    return lines


def why_not(task, my_slots):
    """A note when you can't approve or reject here ('' when you can)."""
    if my_slots:
        return ""
    return task.why_not_sign or "Nothing here is waiting on you."


def reject_problem(comment):
    """Why Reject can't go ahead yet ('' when it can)."""
    return "" if comment.strip() else "Write why you are rejecting it in the comment box. The person who asked will see it."


def approve_question(task, kept_count, handed_names):
    """The question Approve asks."""
    text = f"Approve {kept_count} sign-off{'s' if kept_count != 1 else ''} on {task.label}?"
    if handed_names:
        text += "\n\nHanded to someone else: " + ", ".join(sorted(set(handed_names.values()))) + ". They will see it " \
                "in their My Tasks."
    if task.action in workflow_templates.AUTO_COMPLETE:
        text += f"\n\nIf yours are the last sign-offs, the {workflow_templates.label_of(task.action)} happens straight away."
    return text


def reassign_question(handed_names):
    names = ", ".join(sorted(set(handed_names.values())))
    return f"Hand your sign-offs to {names}? They will see the request in their My Tasks."
