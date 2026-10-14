"""
workflow_templates.py - what a sign-off template is: the actions that can have one (Release, Unrelease,
Void, Make COTS), its rows of roles (a row may accept one of several roles), checking a set of templates is valid,
and the standard ones offered to new vaults.
"""

from dataclasses import dataclass, field

from litterbox.errors import LitterboxError


RELEASE, REOPEN, VOID, MAKE_COTS = "release", "reopen", "void", "make_cots"


ACTIONS = (RELEASE, REOPEN, VOID, MAKE_COTS)          # the actions that can have templates


ACTION_LABEL = {RELEASE: "Release", REOPEN: "Unrelease", VOID: "Void", MAKE_COTS: "Make COTS"}


AUTO_COMPLETE = {RELEASE, REOPEN, VOID}                # done as soon as the last person signs


NEEDS_REASON = {REOPEN, VOID}                          # the request carries a reason


MAX_NAME = 40


MIN_VERSION = "0.3.0"      # the first Litterbox that understands this format; a vault with a workflow requires it


# Offered by "Add standard workflows" in the Workflows window.
STANDARD_WORKFLOWS = {
    RELEASE: [("T1", [["Responsible Engineer"], ["Manufacturing"], ["Analysis"], ["Manager"]]),
              ("T2", [["Responsible Engineer"], ["Manufacturing"]]),
              ("T3", [["Responsible Engineer"]])],
    REOPEN: [("T1", [["Manager", "Chief"]])],
    VOID: [("T1", [["Manager", "Chief"]])],
    MAKE_COTS: [("T1", [["Responsible Engineer"]])],
}


class WorkflowError(LitterboxError):
    """A workflow file or step is wrong, or something isn't allowed. The message is safe to show."""


def label_of(action):
    return ACTION_LABEL.get(action, str(action).replace("_", " ").title())


@dataclass
class Row:
    """One sign-off: somebody holding any of these roles (more than one role means OR)."""
    roles: list

    def text(self):
        return " or ".join(self.roles)


@dataclass
class Template:
    action: str
    name: str
    rows: list = field(default_factory=list)
    allow_same_person: bool = False
    requester_may_sign: bool = True

    def to_dict(self):
        return {"allow_same_person": self.allow_same_person, "requester_may_sign": self.requester_may_sign,
                "signoffs": [{"roles": list(r.roles)} for r in self.rows]}

    @classmethod
    def from_dict(cls, action, name, data):
        where = f"The {label_of(action)} workflow '{name}'"
        if not isinstance(data, dict):
            raise WorkflowError(f"{where} should list its sign-offs.")
        flags = {}
        for key, default in (("allow_same_person", False), ("requester_may_sign", True)):
            value = data.get(key, default)
            if not isinstance(value, bool):
                raise WorkflowError(f"{key} in {where} must be true or false.")
            flags[key] = value
        rows = []
        for item in data.get("signoffs") or []:
            roles = item.get("roles") if isinstance(item, dict) else None
            if not isinstance(roles, list) or not roles or not all(str(r).strip() for r in roles):
                raise WorkflowError(f"Every sign-off in {where} needs a list of roles.")
            rows.append(Row([" ".join(str(r).split()) for r in roles]))
        return cls(action, str(name), rows, **flags)


def tidy_name(name):
    return " ".join(str(name or "").split())


def validate(templates, directory=None):
    """Raise WorkflowError if a template is unusable. With the team directory, roles must be ones the org has
    (their spelling is tidied to match). `templates` is {action: {name: Template}}."""
    for action, named in templates.items():
        label = ACTION_LABEL.get(action)
        if label is None:
            raise WorkflowError(f"'{action}' can't have a workflow. Only {', '.join(ACTION_LABEL.values())} can.")
        seen = set()
        for name, template in named.items():
            where = f"The {label} workflow '{name}'"
            if not tidy_name(name) or len(name) > MAX_NAME:
                raise WorkflowError(f"Each {label} workflow needs a name of up to {MAX_NAME} characters.")
            if name.lower() in seen:
                raise WorkflowError(f"There are two {label} workflows called '{name}'.")
            seen.add(name.lower())
            template.name = name
            if not template.rows:
                raise WorkflowError(f"{where} needs at least one sign-off.")
            for row in template.rows:
                if not row.roles:
                    raise WorkflowError(f"Every sign-off in {where} needs at least one role.")
                if len({r.lower() for r in row.roles}) != len(row.roles):
                    raise WorkflowError(f"A sign-off in {where} lists the same role twice.")
                if directory is not None:
                    fixed = []
                    for role in row.roles:
                        match = next((r for r in directory.roles if r.lower() == role.lower()), None)
                        if match is None:
                            raise WorkflowError(f"'{role}' isn't one of this org's roles. Add it in Team... > "
                                                "Roles first.")
                        fixed.append(match)
                    row.roles = fixed
