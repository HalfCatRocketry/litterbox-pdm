"""
workflow_templates.py - what a sign-off template is: the actions that can have one (Release, Unrelease,
Void, Make COTS and Remove document link for parts; Release, Unrelease and Void for documents, with templates of
their own), its rows of roles (a row may accept one of several roles), checking a set of templates is valid, and the
standard ones offered to new vaults.

A document's action is the part action of the same name with "_document" after it (base_action() gives the part
action, so the same checks and changes apply). for_targets() picks the right one for what is selected.
"""

from dataclasses import dataclass, field

from litterbox import version
from litterbox.errors import LitterboxError


RELEASE, REOPEN, VOID, MAKE_COTS = "release", "reopen", "void", "make_cots"


REMOVE_DOC = "remove_document"     # take a document's link off a released part revision (always needs sign-offs)


RELEASE_DOC, REOPEN_DOC, VOID_DOC = "release_document", "reopen_document", "void_document"


DOC_ACTION = {RELEASE: RELEASE_DOC, REOPEN: REOPEN_DOC, VOID: VOID_DOC}     # a part action -> a document's


ACTIONS = (RELEASE, REOPEN, VOID, MAKE_COTS, REMOVE_DOC, RELEASE_DOC, REOPEN_DOC, VOID_DOC)   # can have templates


# The two Workflows windows (Team > Part Workflows... and Doc Workflows...). Remove document link acts on a part's
# record, but it is about documents, so it is with theirs.
PART_ACTIONS = (RELEASE, REOPEN, VOID, MAKE_COTS)
DOCUMENT_ACTIONS = (RELEASE_DOC, REOPEN_DOC, VOID_DOC, REMOVE_DOC)


ACTION_LABEL = {RELEASE: "Release", REOPEN: "Unrelease", VOID: "Void", MAKE_COTS: "Make COTS",
                REMOVE_DOC: "Remove document link", RELEASE_DOC: "Release document",
                REOPEN_DOC: "Unrelease document", VOID_DOC: "Void document"}


AUTO_COMPLETE = {RELEASE, REOPEN, VOID, MAKE_COTS, REMOVE_DOC, RELEASE_DOC, REOPEN_DOC,
                 VOID_DOC}                                       # done when the last person signs (all of them, since 0.5.4)


NEEDS_REASON = {REOPEN, VOID, REMOVE_DOC, REOPEN_DOC, VOID_DOC}                        # the request carries a reason


def base_action(action):
    """The part action a document's action works like: 'release_document' -> 'release'. Others are themselves."""
    return {doc: part for part, doc in DOC_ACTION.items()}.get(action, action)


def for_targets(action, numbers):
    """The action to use for these targets: a document's own when every one is a document (core/doc_number.py),
    else `action`. Raises WorkflowError for parts and documents together."""
    from litterbox.core.doc_number import DocNumber
    documents = [isinstance(n, DocNumber) for n in numbers]
    if documents and all(documents) and action in DOC_ACTION:
        return DOC_ACTION[action]
    if any(documents) and not all(documents):
        raise WorkflowError("Select parts or documents, not both at once.")
    return action


MAX_NAME = 40


MIN_VERSION = "0.3.0"      # the first Litterbox that understands this format; a vault with a workflow requires it
ECO_MIN_VERSION = "0.4.0"  # the first that understands "Require ECO" (change_orders/); a vault using it requires it
DOC_MIN_VERSION = "0.5.1"  # the first that knows the document actions and Remove document link


# Offered by "Add standard workflows" in the Workflows window. Those in STANDARD_REQUIRE_ECO ask for an ECO.
STANDARD_WORKFLOWS = {
    RELEASE: [("T1", [["Responsible Engineer"], ["Manufacturing"], ["Analysis"], ["Manager"]]),
              ("T2", [["Responsible Engineer"], ["Manufacturing"]]),
              ("T3", [["Responsible Engineer"]])],
    REOPEN: [("T1", [["Manager", "Chief"]])],
    VOID: [("T1", [["Manager", "Chief"]])],
    MAKE_COTS: [("T1", [["Responsible Engineer"]])],
    REMOVE_DOC: [("T1", [["Manager", "Chief"]])],
    RELEASE_DOC: [("T1", [["Responsible Engineer"], ["Manager"]])],
    REOPEN_DOC: [("T1", [["Manager", "Chief"]])],
    VOID_DOC: [("T1", [["Manager", "Chief"]])],
}
STANDARD_REQUIRE_ECO = {(RELEASE, "T1")}


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


TEMPLATE_FIELDS = {"allow_same_person", "requester_may_sign", "require_eco", "signoffs"}


@dataclass
class Template:
    action: str
    name: str
    rows: list = field(default_factory=list)
    allow_same_person: bool = False
    requester_may_sign: bool = True
    require_eco: bool = False           # starting it asks for an engineering change order (change_orders/)
    extra: dict = field(default_factory=dict)   # fields a newer Litterbox wrote, kept so nothing is lost

    def to_dict(self):
        data = {"allow_same_person": self.allow_same_person, "requester_may_sign": self.requester_may_sign}
        if self.require_eco:                    # only written when on, so older files stay as they were
            data["require_eco"] = True
        data["signoffs"] = [{"roles": list(r.roles)} for r in self.rows]
        data.update({k: v for k, v in self.extra.items() if k not in data})
        return data

    @classmethod
    def from_dict(cls, action, name, data):
        where = f"The {label_of(action)} workflow '{name}'"
        if not isinstance(data, dict):
            raise WorkflowError(f"{where} should list its sign-offs.")
        flags = {}
        for key, default in (("allow_same_person", False), ("requester_may_sign", True), ("require_eco", False)):
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
        extra = {k: v for k, v in data.items() if k not in TEMPLATE_FIELDS}
        return cls(action, str(name), rows, **flags, extra=extra)


def min_version_for(templates, running):
    """The oldest Litterbox a vault with these templates needs (`templates` is {action: {name: Template}}), but
    never newer than the one running (`running`, version.VERSION), which must still be able to open the vault."""
    uses_eco = any(t.require_eco for named in templates.values() for t in named.values())
    uses_docs = any(named and action in (REMOVE_DOC, *DOC_ACTION.values()) for action, named in templates.items())
    wanted = DOC_MIN_VERSION if uses_docs else ECO_MIN_VERSION if uses_eco else MIN_VERSION
    return running if version.parse(wanted) > version.parse(running) else wanted


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
                            raise WorkflowError(f"'{role}' isn't one of this org's roles. Add it in Team > "
                                                "Roles first.")
                        fixed.append(match)
                    row.roles = fixed
