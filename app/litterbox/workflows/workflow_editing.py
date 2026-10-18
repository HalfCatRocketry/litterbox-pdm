"""
workflow_editing.py - changing templates in memory (add, rename, remove, apply a list of edits, add the
standard ones), and who in the team could fill a template's rows.
"""

from litterbox.workflows import workflow_templates


def person_can_fill(person, roles):
    held = {r.lower() for r in person.roles}
    return person.active and any(r.lower() in held for r in roles)


def eligible(directory, roles):
    """The active people who hold any of these roles, in the team list's order."""
    return [p for p in directory.people if person_can_fill(p, roles)]


def _matchable(rows, directory):
    """True if each row can be given a different person (a tiny bipartite match)."""
    options = [[p.id for p in eligible(directory, r.roles)] for r in rows]
    taken = {}

    def place(i, seen):
        for pid in options[i]:
            if pid in seen:
                continue
            seen.add(pid)
            if pid not in taken or place(taken[pid], seen):
                taken[pid] = i
                return True
        return False

    return all(place(i, set()) for i in range(len(rows)))


def role_warnings(template, directory):
    """Sentences about sign-offs nobody could fill (a request would wait for an override)."""
    warnings = []
    for number, row in enumerate(template.rows, 1):
        if not eligible(directory, row.roles):
            warnings.append(f"Sign-off {number} ({row.text()}): nobody active has the role.")
    if not warnings and not template.allow_same_person and not _matchable(template.rows, directory):
        warnings.append("There aren't enough different people with these roles to fill every sign-off, and one "
                        "person may not fill more than one.")
    return warnings


def set_template(templates, action, name, rows, allow_same_person=False, requester_may_sign=True, old_name=None,
                 require_eco=False):
    """Put a template in `templates`. `rows` is a list of role lists. With old_name, that template is renamed or
    replaced in the same place. For use inside edit_templates() or a staged change."""
    name = workflow_templates.tidy_name(name)
    named = templates.setdefault(action, {})
    template = workflow_templates.Template(action, name, [workflow_templates.Row([" ".join(str(r).split()) for r in roles]) for roles in rows],
                        allow_same_person, requester_may_sign, require_eco)
    others = [k for k in named if k != old_name]
    if any(k.lower() == name.lower() for k in others):
        raise workflow_templates.WorkflowError(f"There is already a {workflow_templates.label_of(action)} workflow called '{name}'.")
    items = [(name, template) if k == old_name else (k, v) for k, v in named.items()]
    if old_name is None or old_name not in named:
        items.append((name, template))
    named.clear()
    named.update(items)


def remove_template(templates, action, name):
    named = templates.get(action, {})
    named.pop(name, None)
    if not named:
        templates.pop(action, None)


def apply_ops(templates, ops):
    """Apply the changes the Workflows window collected (see gui_logic.WorkflowEditor.ops) to `templates`.
    Each op is {'op': 'remove', 'action', 'name'} or {'op': 'set', 'action', 'name', 'rows', 'same',
    'requester', 'old', 'eco'}. Replaying them on newer files keeps what other people changed meanwhile."""
    for op in ops:
        if op["op"] == "remove":
            remove_template(templates, op["action"], op["name"])
        else:
            set_template(templates, op["action"], op["name"], op["rows"], op["same"], op["requester"],
                         old_name=op.get("old"), require_eco=op.get("eco", False))


def add_standard(templates, directory):
    """Add the standard workflows that aren't there yet (by name). Returns the roles they use that the org
    doesn't have, which must be added first (see missing_standard_roles)."""
    for action, items in workflow_templates.STANDARD_WORKFLOWS.items():
        for name, rows in items:
            if name.lower() not in {k.lower() for k in templates.get(action, {})}:
                set_template(templates, action, name, rows,
                             require_eco=(action, name) in workflow_templates.STANDARD_REQUIRE_ECO)
    return missing_standard_roles(directory)


def missing_standard_roles(directory):
    wanted = []
    for items in workflow_templates.STANDARD_WORKFLOWS.values():
        for _name, rows in items:
            for roles in rows:
                for role in roles:
                    if role not in wanted:
                        wanted.append(role)
    have = {r.lower() for r in directory.roles}
    return [r for r in wanted if r.lower() not in have]
