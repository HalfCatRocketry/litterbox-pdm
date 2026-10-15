"""
workflow_editor.py - the Workflows window's working copy (WorkflowEditor): edits are made here and only
saved as a list of operations when you press Save.
"""

from litterbox.workflows import workflow_templates


class WorkflowEditor:
    """What the Workflows window edits: a working copy of every template, with the changes it makes.

        editor = WorkflowEditor(draft.templates)
        editor.add(action) ... editor.add_role(action, index, row) ...
        editor.ops()      # the changes to stage (see workflow_editing.apply_ops); [] if nothing changed
    """

    def __init__(self, templates):
        self.items = {a: [] for a in workflow_templates.ACTIONS}
        for action, named in templates.items():
            for name, t in named.items():
                self.items.setdefault(action, []).append(
                    {"origin": name, "name": name, "rows": [list(r.roles) for r in t.rows],
                     "same": t.allow_same_person, "requester": t.requester_may_sign, "eco": t.require_eco})
        self.initial = self._snapshot()

    def _snapshot(self):
        return {a: [(i["origin"], i["name"], [list(r) for r in i["rows"]], i["same"], i["requester"], i["eco"])
                    for i in items] for a, items in self.items.items()}

    @property
    def dirty(self):
        return self._snapshot() != self.initial

    def names(self, action):
        return [i["name"] for i in self.items[action]]

    def add(self, action, roles):
        """A new template named T<n> (first free) with one sign-off. Returns its index."""
        taken = {n.lower() for n in self.names(action)}
        number = 1
        while f"T{number}".lower() in taken:
            number += 1
        self.items[action].append({"origin": None, "name": f"T{number}", "rows": [[roles[0]] if roles else []],
                                   "same": False, "requester": True, "eco": False})
        return len(self.items[action]) - 1

    def delete(self, action, index):
        del self.items[action][index]

    def add_row(self, action, index, roles):
        self.items[action][index]["rows"].append([roles[0]] if roles else [])

    def remove_row(self, action, index, row):
        del self.items[action][index]["rows"][row]

    def add_or(self, action, index, row, roles):
        """Another role the sign-off may be filled from (the first one not used already, or None)."""
        used = self.items[action][index]["rows"][row]
        spare = next((r for r in roles if r.lower() not in {u.lower() for u in used}), None)
        if spare is not None:
            used.append(spare)
        return spare

    def remove_or(self, action, index, row, position):
        roles = self.items[action][index]["rows"][row]
        if len(roles) > 1:
            del roles[position]

    def set_role(self, action, index, row, position, role):
        self.items[action][index]["rows"][row][position] = role

    def problem(self):
        """'' or the first thing wrong, in words for the window."""
        for action, items in self.items.items():
            seen = set()
            for item in items:
                where = f"{workflow_templates.label_of(action)} workflow '{item['name']}'"
                if not workflow_templates.tidy_name(item["name"]):
                    return f"Every {workflow_templates.label_of(action)} workflow needs a name."
                if len(item["name"]) > workflow_templates.MAX_NAME:
                    return f"The name of {where} is too long."
                if item["name"].strip().lower() in seen:
                    return f"There are two {workflow_templates.label_of(action)} workflows called '{item['name']}'."
                seen.add(item["name"].strip().lower())
                if not item["rows"]:
                    return f"{where} needs at least one sign-off."
                for number, roles in enumerate(item["rows"], 1):
                    if not roles:
                        return f"Sign-off {number} of {where} needs a role."
                    if len({r.lower() for r in roles}) != len(roles):
                        return f"Sign-off {number} of {where} lists the same role twice."
        return ""

    def templates(self):
        """The working copy as {action: {name: Template}} (for warnings)."""
        result = {}
        for action, items in self.items.items():
            for i in items:
                result.setdefault(action, {})[i["name"].strip()] = workflow_templates.Template(
                    action, i["name"].strip(), [workflow_templates.Row(list(r)) for r in i["rows"]], i["same"], i["requester"],
                    i["eco"])
        return result

    def ops(self):
        """The changes made, in an order that works when replayed: removals, then sets in list order."""
        removals, sets = [], []
        for action, items in self.items.items():
            kept = {i["origin"] for i in items if i["origin"] is not None}
            initial = {o for o, *_rest in self.initial[action] if o is not None}
            removals += [{"op": "remove", "action": action, "name": origin} for origin in sorted(initial - kept)]
            before = {o: (n, r, sm, rq, eco) for o, n, r, sm, rq, eco in self.initial[action]}
            for i in items:
                now = (i["name"].strip(), [list(r) for r in i["rows"]], i["same"], i["requester"], i["eco"])
                if i["origin"] is None or before.get(i["origin"]) != now:
                    sets.append({"op": "set", "action": action, "name": i["name"].strip(), "rows": now[1],
                                 "same": i["same"], "requester": i["requester"], "eco": i["eco"],
                                 "old": i["origin"]})
        return removals + sets

    def add_standard(self, roles):
        """Add the standard workflows whose roles all exist; returns (added names, [(name, missing roles)])."""
        have = {r.lower() for r in roles}
        added, skipped = [], []
        for action, items in workflow_templates.STANDARD_WORKFLOWS.items():
            for name, rows in items:
                if name.lower() in {n.lower() for n in self.names(action)}:
                    continue
                missing = [r for row in rows for r in row if r.lower() not in have]
                if missing:
                    skipped.append((f"{workflow_templates.label_of(action)} {name}", sorted(set(missing))))
                    continue
                self.items[action].append({"origin": None, "name": name, "rows": [list(r) for r in rows],
                                           "same": False, "requester": True,
                                           "eco": (action, name) in workflow_templates.STANDARD_REQUIRE_ECO})
                added.append(f"{workflow_templates.label_of(action)} {name}")
        return added, skipped


def ops_label(ops):
    """The Team window's name for a staged Workflows change."""
    if not ops:
        return "Workflows"
    actions = []
    for op in ops:
        label = workflow_templates.label_of(op["action"])
        if label not in actions:
            actions.append(label)
    return "Workflows: " + ", ".join(actions)
