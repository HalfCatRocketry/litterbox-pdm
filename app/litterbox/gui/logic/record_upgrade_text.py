"""
record_upgrade_text.py - what the window says about upgrading the vault's records to a newer record format
(vault/record_upgrade.py): the question before it, and the messages around it.
"""

ASK_AN_ADMIN = ("This Litterbox keeps part records in a newer format, and this vault hasn't been upgraded to it yet, so "
                "nothing can be changed until it is. An Admin or the Owner can upgrade it (Vault > Upgrade records...).")

UP_TO_DATE = "This vault's records are up to date."

NOT_NOW = "The records were not upgraded. Vault > Upgrade records... does it later."


def _count(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def question(plan):
    """The question before an upgrade. plan: a vault/record_upgrade.Plan."""
    text = []
    if plan.outdated:
        text.append(f"This Litterbox keeps part records in a newer format. {_count(len(plan.outdated), 'record')} in "
                    "this vault are in an older one.")
    else:
        text.append("This Litterbox keeps part records in a newer format, and this vault doesn't allow it yet.")
    if plan.steps:
        text += ["", "What changes:", *(f"- {step.what} ({_count(n, 'record')})" for step, n in plan.steps)]
    if plan.raise_minimum:
        text += ["", f"Everyone will need Litterbox {plan.raise_minimum} or newer to work in this vault. Older copies "
                     "can't read the new format, so they will be told to update."]
    if plan.checked_out:
        shown = ", ".join(str(pn) for pn in plan.checked_out[:5])
        more = f" and {len(plan.checked_out) - 5} more" if len(plan.checked_out) > 5 else ""
        text += ["", f"Checked out, so left until they are checked in: {shown}{more}."]
    text += ["", "Upgrade the records now? The change is uploaded for everyone."]
    return "\n".join(text)


def done_text(result):
    """The status line after an upgrade. result: a vault/record_upgrade.Result."""
    parts = [f"{_count(result.rewritten, 'record')} upgraded" if result.rewritten else "Records upgraded"]
    if result.checked_out:
        parts.append(f"{_count(len(result.checked_out), 'checked-out record')} left until checked in")
    if result.errors:
        parts.append(f"{_count(len(result.errors), 'record')} couldn't be done (see the Log)")
    return "; ".join(parts)
