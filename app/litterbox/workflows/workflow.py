"""
workflow.py - sign-offs before a part's status changes.

An Admin can say "a release (or unrelease, void, make COTS) needs sign-offs". After that, pressing the button no
longer does it: it opens the Workflow window, where you pick a template and a person for each sign-off. The
people named approve (or reject), and when everyone has signed the action happens.

THE TEMPLATES   .litterbox/workflows.yaml, shared through Git like the team file. Admins edit it (Team... >
    Workflows...). Each action can have several named templates (T1, T2... or your own):

        workflows:
          release:
            T1:
              allow_same_person: false      one person may fill more than one row (default false)
              requester_may_sign: true      the person who asked may be one of the signers (default true)
              signoffs:
              - roles: [Responsible Engineer]
              - roles: [Manager, Chief]     OR: a Manager or a Chief may fill this row
              - roles: [Responsible Engineer]   a role listed twice is two sign-offs

    An action with no templates works as it always did (it just happens).

THE REQUEST   One request can cover several parts (a batch). It is saved in each part's record under `pending`:
    id (the same for the whole batch), action, revision, requested_by (+ _id, _at), template_name and the
    template AS IT WAS (editing it later changes nothing in flight), reason (reopen / void), parts, the hash of
    every CAD file, `slots` (one per sign-off row: the roles allowed, and the person named) and `signoffs` (who
    signed which slot, and when). A part with a pending request can't be checked out or changed, so what gets
    approved is what happens.

THE STEPS     request -> sign_off (each named person) -> complete
    The last sign-off completes the action straight away for release, reopen and void. Make COTS waits for
    someone to press the button again. If completing fails (offline, behind the vault...) the sign-off is still
    saved and the part shows "approved, ready".
    reject      a named signer (or Admin) sends the whole batch back with a comment.
    withdraw    the requester (or Admin) cancels the batch.
    reassign    the requester (or Admin) swaps the person named for a sign-off that hasn't been given.
    override    an Admin does the action without the sign-offs. A reason is required and it is recorded.

THE TRAIL     A finished action adds an entry to the record's `approvals`: who asked, the template, who signed
    (with roles and times), the file hashes, and any override with its reason. Every step is in the history too.

Everything here that changes a record uses the same lock, pull, change, commit, push, unlock routine as the rest
of Litterbox (litterbox_engine._edit_record). A batch is done one part at a time; if a step fails part-way, the
parts already done stay done, and the message says which.
"""

import copy
import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from litterbox.vault import config
from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox.records import registry

WORKFLOWS_FILE = ".litterbox/workflows.yaml"
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


class WorkflowError(eng.LitterboxError):
    """A workflow file or step is wrong, or something isn't allowed. The message is safe to show."""


def label_of(action):
    return ACTION_LABEL.get(action, str(action).replace("_", " ").title())


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

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


def load(repo):
    """The vault's templates as {action: {name: Template}}. No file means no workflows."""
    path = Path(repo) / WORKFLOWS_FILE
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise WorkflowError(f"Could not read {WORKFLOWS_FILE}: {e}")
    if data in (None, ""):
        return {}
    flows = data.get("workflows") if isinstance(data, dict) else None
    if flows in (None, ""):
        return {}
    if not isinstance(flows, dict):
        raise WorkflowError(f"{WORKFLOWS_FILE} should contain 'workflows:' followed by the actions.")
    templates = {}
    for action, body in flows.items():
        if not isinstance(body, dict) or "signoffs" in body:
            raise WorkflowError(f"{WORKFLOWS_FILE} is in the format of Litterbox 0.2. Delete the file (or the "
                                f"'{action}' part) and set the workflows up again in Team... > Workflows.")
        templates[str(action)] = {str(name): Template.from_dict(str(action), name, t) for name, t in body.items()}
    validate(templates)
    return templates


def save(repo, templates):
    path = Path(repo) / WORKFLOWS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"workflows": {action: {name: t.to_dict() for name, t in named.items()}
                          for action, named in sorted(templates.items()) if named}}
    tmp = path.with_name(".tmp-workflows.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(body, f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)


def templates_for(repo, action):
    """{name: Template} for this action; empty if it needs no sign-offs."""
    return load(repo).get(action, {})


def has_templates(repo, action):
    return bool(templates_for(repo, action))


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

@eng._converts_errors
def edit_templates(repo, change, message):
    """Change the workflow file for everyone: lock it, get the latest, `change(templates, directory)`, check,
    commit, push, unlock. If anything fails the file is put back. Admins only. Returns what change() returns."""
    eng.validate_repo(repo)
    identity = people.require(repo, "manage_workflows")
    if identity.state != people.OK:
        raise WorkflowError("Set up the team first (Team... > Set Up Team): workflows are about people's roles.")
    rel = WORKFLOWS_FILE
    config_rel = f"{config.CONFIG_DIR}/{config.CONFIG_FILE}"
    existed = people._tracked(repo, rel)
    config_tracked = people._tracked(repo, config_rel)
    config_before = (Path(repo) / config_rel).read_bytes() if (Path(repo) / config_rel).is_file() else None
    if existed:
        eng._lock(repo, rel, "the workflows file")
    committed, result = False, None
    try:
        eng._pull(repo)
        templates = load(repo)
        directory = people.load(repo)
        result = change(templates, directory)
        validate(templates, directory)
        save(repo, templates)
        paths = [rel]
        if templates:
            # Older versions don't know about pending requests and would let a part slip past its sign-offs, so
            # the vault now asks everyone to update before working in it.
            config.stamp(repo, min_version=MIN_VERSION)
            paths.append(config_rel)
        eng.run(["git", "add", "--"] + paths, repo)
        eng.run(["git", "commit", "-m", message, "--"] + paths, repo)
        committed = True
        eng._push_with_retry(repo)
    except BaseException:
        try:
            if committed:
                eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
            if config_tracked:
                eng.run(["git", "restore", "--staged", "--worktree", "--", config_rel], repo)
            else:
                eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", config_rel], repo, quiet=True)
                try:
                    if config_before is None:
                        (Path(repo) / config_rel).unlink()
                    else:
                        (Path(repo) / config_rel).write_bytes(config_before)       # an untracked file of theirs
                except OSError:
                    pass
            if existed:
                eng.run(["git", "restore", "--staged", "--worktree", "--", rel], repo)
            else:
                eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", rel], repo, quiet=True)
                try:
                    (Path(repo) / rel).unlink()
                except OSError:
                    pass
        except eng.LitterboxError as e:
            eng.LOG(f"WARNING: could not fully undo the change to {rel}: {e}")
        if existed:
            eng._force_unlock_quietly(repo, [rel])
        raise
    if existed:
        failed = eng._unlock_mine(repo, [rel])
        if failed:
            raise eng.LitterboxError(eng._unlock_failure_message(failed))
    return result



def set_template(templates, action, name, rows, allow_same_person=False, requester_may_sign=True, old_name=None):
    """Put a template in `templates`. `rows` is a list of role lists. With old_name, that template is renamed or
    replaced in the same place. For use inside edit_templates() or a staged change."""
    name = tidy_name(name)
    named = templates.setdefault(action, {})
    template = Template(action, name, [Row([" ".join(str(r).split()) for r in roles]) for roles in rows],
                        allow_same_person, requester_may_sign)
    others = [k for k in named if k != old_name]
    if any(k.lower() == name.lower() for k in others):
        raise WorkflowError(f"There is already a {label_of(action)} workflow called '{name}'.")
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
    'requester', 'old'}. Replaying them on newer files keeps what other people changed meanwhile."""
    for op in ops:
        if op["op"] == "remove":
            remove_template(templates, op["action"], op["name"])
        else:
            set_template(templates, op["action"], op["name"], op["rows"], op["same"], op["requester"],
                         old_name=op.get("old"))


def add_standard(templates, directory):
    """Add the standard workflows that aren't there yet (by name). Returns the roles they use that the org
    doesn't have, which must be added first (see missing_standard_roles)."""
    for action, items in STANDARD_WORKFLOWS.items():
        for name, rows in items:
            if name.lower() not in {k.lower() for k in templates.get(action, {})}:
                set_template(templates, action, name, rows)
    return missing_standard_roles(directory)


def missing_standard_roles(directory):
    wanted = []
    for items in STANDARD_WORKFLOWS.values():
        for _name, rows in items:
            for roles in rows:
                for role in roles:
                    if role not in wanted:
                        wanted.append(role)
    have = {r.lower() for r in directory.roles}
    return [r for r in wanted if r.lower() not in have]


# ---------------------------------------------------------------------------
# A pending request: how far along is it?
# ---------------------------------------------------------------------------

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
    label = label_of(pending.get("action"))
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


def _is_admin(person):
    return person.access in (people.OWNER, people.ADMIN)


def _is_signer(pending, person):
    return any(s.get("id") == person.id for s in pending["slots"])


def may_sign(pending, person):
    """(True, '') or (False, why not) for this person signing this request."""
    if open_slots(pending, person.id):
        return True, ""
    if is_complete(pending):
        return False, "Everyone needed has already signed."
    if _is_signer(pending, person):
        return False, "You have already signed everything that was asked of you."
    return False, "You are not one of the people named to sign this."


# ---------------------------------------------------------------------------
# Doing things
# ---------------------------------------------------------------------------

def file_hashes(repo, files):
    """{file: sha256} for CAD files (paths relative to the vault)."""
    result = {}
    for rel in files:
        path = Path(repo) / rel
        if eng.is_pointer(path):
            raise WorkflowError(f"{rel} hasn't been downloaded. Run Get Latest.")
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as e:
            raise WorkflowError(f"Could not read {rel}: {e}")
        result[rel] = digest.hexdigest()
    return result


def _me(repo, action):
    """The current user as a team member. Workflows are about people, so a vault with no team can't use them."""
    identity = people.require(repo, action)
    if identity.state != people.OK or identity.person is None:
        raise WorkflowError("Set up the team first (Team... > Set Up Team): sign-offs are done by people on it.")
    return identity.person


def _pending_of(record, batch_id=None):
    if not record.pending:
        raise WorkflowError(f"{record.pn} has no request waiting for sign-offs. Run Get Latest in case it was "
                            "already dealt with.")
    if batch_id and record.pending.get("id") != batch_id:
        raise WorkflowError(f"{record.pn} is now in a different request. Run Get Latest.")
    if record.pending.get("revision") != record.revision:
        raise WorkflowError(f"The request for {record.pn} is for Rev {record.pending.get('revision')}, which is no "
                            "longer the working revision. Withdraw it.")
    return record.pending


def _check_files_unchanged(repo, pending):
    if not pending.get("files"):
        return
    now = file_hashes(repo, list(pending["files"]))
    for rel, digest in pending["files"].items():
        if now.get(rel) != digest:
            raise WorkflowError(f"{rel} is different from the file the sign-offs were asked for. Withdraw the "
                                "request and ask again. If you think your copy is behind, run Get Latest.")


def _as_pns(pns):
    if not isinstance(pns, (list, tuple, set)):
        pns = [pns]
    return [eng._as_pn(p) for p in pns]


def _problems(repo, pn, action, reason, fetch, ctx=None):
    """(problems, files) for starting `action` on this part."""
    if action == RELEASE:
        plan = eng.release_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    if action == MAKE_COTS:
        plan = eng.make_cots_plan(repo, pn, fetch=fetch, ctx=ctx)
        return list(plan.problems), list(plan.files)
    record = registry.load(repo, pn)
    if record.pending:
        return ["It is already waiting for sign-offs."], []
    trial = copy.deepcopy(record)
    try:
        if action == REOPEN:
            registry.mark_reopened(trial, "check", reason or "check")
        else:
            registry.mark_void(trial, "check", reason or "check")
    except registry.RegistryError as e:
        return [str(e)], []
    return [], []


def build_slots(template, directory, requester_id, assignments, extras=()):
    """The `slots` for a request: one per template row (the person named in `assignments`, in order) and one
    per extra (role, person id). Raises WorkflowError for anything the template doesn't allow."""
    if len(assignments) != len(template.rows):
        raise WorkflowError("Choose a person for every sign-off.")
    slots = []
    for number, (row, pid) in enumerate(zip(template.rows, assignments), 1):
        slots.append(_slot(directory, row.roles, pid, f"sign-off {number} ({row.text()})", False))
    for role, pid in extras:
        roles = [role] if isinstance(role, str) else list(role)
        match = [next((r for r in directory.roles if r.lower() == x.lower()), None) for x in roles]
        if not roles or None in match:
            raise WorkflowError("An extra sign-off needs one of this org's roles.")
        slots.append(_slot(directory, match, pid, f"the extra {' or '.join(match)} sign-off", True))
    ids = [s["id"] for s in slots]
    if not template.allow_same_person and len(set(ids)) != len(ids):
        raise WorkflowError(f"The {template.name} workflow doesn't let one person fill more than one sign-off. "
                            "Choose different people.")
    if not template.requester_may_sign and requester_id in ids:
        raise WorkflowError(f"The {template.name} workflow doesn't let you sign your own request. Choose someone "
                            "else for the sign-off.")
    return slots


def _slot(directory, roles, person_id, where, extra):
    person = directory.get(person_id) if person_id else None
    if person is None:
        raise WorkflowError(f"Choose a person for {where}.")
    if not person_can_fill(person, roles):
        raise WorkflowError(f"{person.name} is not active with the role needed for {where}.")
    return {"roles": list(roles), "id": person.id, "name": person.name, **({"extra": True} if extra else {})}


@eng._converts_errors
def request(repo, pns, action, template_name, assignments, extras=(), reason=""):
    """Start a workflow on one or more parts: check every part first (nothing happens if any can't go ahead),
    then record the request in each. Returns the new request's id."""
    pns = _as_pns(pns)
    if action not in ACTIONS:
        raise WorkflowError(f"'{action}' can't have a workflow.")
    me = _me(repo, action)
    template = templates_for(repo, action).get(template_name)
    if template is None:
        raise WorkflowError(f"There is no {label_of(action)} workflow called '{template_name}'. Run Get Latest.")
    directory = people.load(repo)
    slots = build_slots(template, directory, me.id, assignments, extras)
    reason = " ".join((reason or "").split())
    if action in NEEDS_REASON and not reason:
        raise WorkflowError(f"A reason is required to {label_of(action).lower()} a part.")
    if not pns:
        raise WorkflowError("Choose at least one part.")

    problems, files, ctx = {}, {}, eng._Context(repo)         # the vault is looked at once for all the parts
    for pn in pns:
        found, cad = _problems(repo, pn, action, reason, True, ctx)
        if found:
            problems[pn] = found
        files[pn] = cad
    if problems:
        raise WorkflowError("These can't go ahead yet:\n\n" + "\n".join(
            f"{pn}:\n  - " + "\n  - ".join(found) for pn, found in problems.items()))
    hashes = {pn: file_hashes(repo, files[pn]) for pn in pns}

    batch_id = uuid.uuid4().hex[:8]
    items = []
    for pn in pns:
        def edit(record, user, pn=pn):
            if record.pending:
                raise registry.RegistryError(f"{record.pn} already has a request waiting for sign-offs.")
            if action == RELEASE and (record.status != registry.STATUS_IN_WORK or record.cots):
                raise registry.RegistryError(f"Cannot release {record.pn}: its status is '{record.status}'.")
            record.pending = {
                "id": batch_id, "action": action, "revision": record.revision, "requested_by": user,
                "requested_by_id": me.id, "requested_at": registry.now_utc(), "template_name": template.name,
                "template": template.to_dict(), "parts": [str(p) for p in pns], "slots": copy.deepcopy(slots),
                "files": dict(hashes[pn]), "signoffs": [],
                **({"reason": reason} if reason else {}),
            }
            registry.add_event(record, registry.EVENT_RELEASE_REQUESTED, user, action=action,
                               waiting_on=waiting_on(record.pending), files=list(files[pn]) or None,
                               reason=reason or None)
        items.append((pn, action, edit, f"{pn}: {label_of(action)} requested"))
    try:
        batch = eng._edit_records(repo, items, atomic=True)      # all or nothing: one download, one upload
    except (eng.LitterboxError, registry.RegistryError) as e:
        raise WorkflowError(f"Could not start the workflow, so nothing was changed:\n\n{e}")
    if batch.notice:
        eng.LOG(batch.notice)
    return batch_id


@dataclass
class SignResult:
    signed: list = field(default_factory=list)       # parts you signed on
    completed: list = field(default_factory=list)    # parts where the action went through
    errors: dict = field(default_factory=dict)       # {pn: why} for parts where something failed
    summary: str = ""


@eng._converts_errors
def sign_off(repo, pns, comment=""):
    """Approve, as the person named, every sign-off waiting for you on these parts. When a part then has all its
    sign-offs, release / reopen / void happens straight away; if that fails the sign-off is still saved.
    All the parts are signed with one download and one upload, and finished together."""
    pns = _as_pns(pns)
    me = _me(repo, "signoff")
    comment = " ".join((comment or "").split())
    result = SignResult()
    items = []
    for pn in pns:
        try:
            record = registry.load(repo, pn)
        except registry.RegistryError as e:
            result.errors[pn] = str(e)
            continue
        if not record.pending or not open_slots(record.pending, me.id):
            continue                                            # nothing left for you here (or already done)

        def edit(record, user, batch_id=record.pending.get("id")):
            pending = _pending_of(record, batch_id)
            mine = open_slots(pending, me.id)
            if not mine:
                raise registry.RegistryError(f"You have nothing left to sign on {record.pn}.")
            _check_files_unchanged(repo, pending)
            for index in mine:
                pending["signoffs"].append({"slot": index, "by": user, "id": me.id, "roles": pending["slots"][index]
                                            ["roles"], "at": registry.now_utc(),
                                            **({"comment": comment} if comment else {})})
            registry.add_event(record, registry.EVENT_RELEASE_SIGNED, user, action=pending["action"],
                               roles=[" or ".join(pending["slots"][i]["roles"]) for i in mine],
                               comment=comment or None, waiting_on=waiting_on(pending) or None)

        items.append((pn, "signoff", edit, f"{pn}: signed off"))
    if items:
        batch = eng._edit_records(repo, items)
        result.signed = list(batch.results)
        result.errors.update({pn: str(e) for pn, e in batch.errors.items()})
        if batch.notice:
            eng.LOG(batch.notice)

    finishing = []
    for pn in result.signed:
        try:
            record = registry.load(repo, pn)
        except registry.RegistryError as e:
            result.errors[pn] = str(e)
            continue
        if record.pending and is_complete(record.pending) and record.pending["action"] in AUTO_COMPLETE:
            finishing.append(pn)
    if finishing:
        try:
            done, failed, _files = _finish_many(repo, finishing)
        except eng.LitterboxError as e:
            failed, done = {pn: e for pn in finishing}, []
        result.completed = done
        result.errors.update({pn: str(e) for pn, e in failed.items()})
    if not result.signed and not result.errors:
        raise WorkflowError("There was nothing for you to sign on these parts. Run Get Latest.")
    if not result.signed and result.errors:
        raise WorkflowError("\n".join(f"{pn}: {why}" for pn, why in result.errors.items()))
    result.summary = f"Signed off {len(result.signed)} part{'s' if len(result.signed) != 1 else ''}"
    return result


def _approval_entry(pending, completed_by, override=None, files=None, action=None, reason=None):
    entry = {"action": action, "revision": pending.get("revision") if pending else None}
    if pending:
        entry.update({"requested_by": pending.get("requested_by"), "requested_at": pending.get("requested_at"),
                      "template_name": pending.get("template_name"), "template": pending.get("template"),
                      "slots": pending.get("slots"), "signoffs": list(pending.get("signoffs", [])),
                      "files": dict(pending.get("files", {})), "parts": pending.get("parts")})
    else:
        entry.update({"signoffs": [], "files": dict(files or {})})
    if reason:
        entry["reason"] = reason
    entry["completed_by"] = completed_by
    entry["completed_at"] = registry.now_utc()
    if override:
        entry["override"] = override
    return {k: v for k, v in entry.items() if v is not None}


def _finish_edit(repo, action, plan, override_reason):
    """The change that does the action on a record. Shared by complete() and override()."""
    def edit(record, user):
        pending = record.pending or None
        if override_reason is None:
            pending = _pending_of(record)
            if not is_complete(pending):
                raise registry.RegistryError("Still waiting for: " + ", ".join(waiting_on(pending)) + ".")
            _check_files_unchanged(repo, pending)
        act = pending["action"] if pending else action
        reason = (pending or {}).get("reason") or override_reason
        signed = [e.get("by") for e in (pending or {}).get("signoffs", [])]
        details, override = {"signoffs": signed or None}, None
        if override_reason is not None:
            missing = waiting_on(pending) if pending else ["every sign-off"]
            override = {"by": user, "reason": override_reason, "missing": missing}
            details.update(override=True, reason=override_reason)
        files = file_hashes(repo, plan.files) if (plan is not None and not pending) else None
        approval = _approval_entry(pending, user, override, files, act, reason)
        record.pending = {}                                    # the checks in mark_* refuse a pending part
        if act == RELEASE:
            registry.mark_released(record, user, plan.files, **details)
        elif act == MAKE_COTS:
            registry.mark_cots(record, user, plan.files)
        elif act == REOPEN:
            registry.mark_reopened(record, user, reason)
        else:
            registry.mark_void(record, user, reason)
        record.approvals.append(approval)
    return edit


def _finish_many(repo, pns, override_reason=None, override_action=None):
    """Do the action now on several parts, with one download and one upload (the vault is checked once).
    Returns (done, failed, files): done is [pn], failed is {pn: error}, files is {pn: [files released]}."""
    ctx, failed, items, files = eng._Context(repo), {}, [], {}
    for pn in _as_pns(pns):
        try:
            record0 = registry.load(repo, pn)
            action = record0.pending.get("action") if record0.pending else override_action
            if action not in ACTIONS:
                raise WorkflowError(f"{pn} has no request to complete.")
            plan = None
            if action == RELEASE:
                plan = eng.release_plan(repo, pn, allow_pending=True, ctx=ctx)
            elif action == MAKE_COTS:
                plan = eng.make_cots_plan(repo, pn, allow_pending=True, ctx=ctx)
            if plan is not None and not plan.ok:
                what = "released" if action == RELEASE else "made COTS"
                raise eng.LitterboxError(f"{pn} can't be {what} yet:\n- " + "\n- ".join(plan.problems))
        except (eng.LitterboxError, registry.RegistryError) as e:
            failed[pn] = e
            continue
        message = f"{pn}: {label_of(action)} done" + (" (Admin override)" if override_reason is not None
                                                      else " after sign-offs")
        items.append((pn, action, _finish_edit(repo, action, plan, override_reason), message))
        files[pn] = list(plan.files) if plan is not None else []
    done = []
    if items:
        batch = eng._edit_records(repo, items)
        done = list(batch.results)
        failed.update(batch.errors)
        if batch.notice:
            eng.LOG(batch.notice)
    return done, failed, files


def _report(done, failed):
    if failed:
        raise WorkflowError(("Done on " + ", ".join(map(str, done)) + ".\n\n" if done else "") +
                            "\n".join(f"{pn}: {why}" for pn, why in failed.items()))
    return done


@eng._converts_errors
def complete(repo, pn):
    """Do the action for a part whose request has every sign-off."""
    _me(repo, "signoff")
    done, failed, files = _finish_many(repo, [pn])
    if failed:
        raise next(iter(failed.values()))
    return files[done[0]]


@eng._converts_errors
def complete_many(repo, pns):
    """Do the action for each part whose request has every sign-off, with one download and one upload. Carries on
    past a failure and reports every one at the end."""
    _me(repo, "signoff")
    done, failed, _files = _finish_many(repo, pns)
    return _report(done, {pn: str(e) for pn, e in failed.items()})


@eng._converts_errors
def override(repo, pns, reason, action=None):
    """Admins only: do the action without the sign-offs. A reason is required and is recorded as an override.
    `action` is needed only for a part that has no request."""
    pns = _as_pns(pns)
    _me(repo, "override_release")
    reason = " ".join((reason or "").split())
    if not reason:
        raise WorkflowError("A reason is required to go ahead without sign-offs.")
    done, failed, _files = _finish_many(repo, pns, override_reason=reason, override_action=action)
    return _report(done, {pn: str(e) for pn, e in failed.items()})


def _each(repo, pns, edit_for, action_name, message):
    """Apply a change to every part of a batch that still has a request (parts already dealt with are skipped),
    with one download and one upload."""
    failed, items = {}, []
    for pn in _as_pns(pns):
        try:
            record = registry.load(repo, pn)
        except (eng.LitterboxError, registry.RegistryError) as e:
            failed[pn] = str(e)
            continue
        if record.pending:
            items.append((pn, action_name, edit_for(record.pending.get("id")), message.replace("{pn}", str(pn))))
    done = []
    if items:
        batch = eng._edit_records(repo, items)
        done = list(batch.results)
        failed.update({pn: str(e) for pn, e in batch.errors.items()})
        if batch.notice:
            eng.LOG(batch.notice)
    return _report(done, failed)


@eng._converts_errors
def reject(repo, pns, comment):
    """Send a pending batch back. A person named to sign (or an Admin) may; a comment is required. The parts are
    free to check out again."""
    me = _me(repo, "signoff")
    comment = " ".join((comment or "").split())
    if not comment:
        raise WorkflowError("Say why you are rejecting it, so the person who asked knows what to fix.")

    def edit_for(batch_id):
        def edit(record, user):
            pending = _pending_of(record, batch_id)
            if not (_is_signer(pending, me) or _is_admin(me)):
                raise registry.RegistryError("Only a person named to sign this (or an Admin) can reject it.")
            registry.add_event(record, registry.EVENT_RELEASE_REJECTED, user, action=pending["action"],
                               reason=comment, requested_by=pending.get("requested_by"),
                               signed=[e.get("by") for e in pending["signoffs"]] or None)
            record.pending = {}
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request rejected - " + comment)


@eng._converts_errors
def withdraw(repo, pns, reason=""):
    """Cancel a pending batch. The person who asked, or an Admin, may."""
    me = _me(repo, "signoff")
    reason = " ".join((reason or "").split())

    def edit_for(batch_id):
        def edit(record, user):
            pending = _pending_of(record, batch_id)
            if not (pending.get("requested_by_id") == me.id or _is_admin(me)):
                raise registry.RegistryError("Only the person who asked, or an Admin, can withdraw the request.")
            registry.add_event(record, registry.EVENT_RELEASE_WITHDRAWN, user, action=pending["action"],
                               reason=reason or None, requested_by=pending.get("requested_by"))
            record.pending = {}
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: request withdrawn")


@eng._converts_errors
def reassign(repo, pns, slot, person_id):
    """Name a different person for a sign-off that hasn't been given. The person who asked, or an Admin, may."""
    me = _me(repo, "signoff")
    directory = people.load(repo)

    def edit_for(batch_id):
        def edit(record, user):
            pending = _pending_of(record, batch_id)
            if not (pending.get("requested_by_id") == me.id or _is_admin(me)):
                raise registry.RegistryError("Only the person who asked, or an Admin, can change who signs.")
            if not 0 <= slot < len(pending["slots"]):
                raise registry.RegistryError("That sign-off isn't in the request. Run Get Latest.")
            if slot_done(pending, slot):
                raise registry.RegistryError("That sign-off has already been given.")
            old = pending["slots"][slot]
            new = _slot(directory, old["roles"], person_id, f"the {' or '.join(old['roles'])} sign-off",
                        bool(old.get("extra")))
            template = pending["template"]
            ids = [s["id"] for i, s in enumerate(pending["slots"]) if i != slot] + [new["id"]]
            if not template.get("allow_same_person", False) and len(set(ids)) != len(ids):
                raise registry.RegistryError(f"This workflow doesn't let one person fill more than one sign-off.")
            if not template.get("requester_may_sign", True) and new["id"] == pending.get("requested_by_id"):
                raise registry.RegistryError("This workflow doesn't let the person who asked sign.")
            pending["slots"][slot] = new
            registry.add_event(record, registry.EVENT_REASSIGNED, user, action=pending["action"],
                               roles=[" or ".join(new["roles"])], reason=f"{old['name']} replaced by {new['name']}")
        return edit

    return _each(repo, pns, edit_for, "signoff", "{pn}: signer changed")


# ---------------------------------------------------------------------------
# My Tasks
# ---------------------------------------------------------------------------

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
    me = identity.person if identity.state == people.OK else None
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
        done = [all(slot_done(p, i) for p in pendings) for i in range(len(first["slots"]))]
        slots = [{"text": slot_text(s), "name": s["name"], "id": s.get("id"), "done": done[i], "roles": list(s["roles"])}
                 for i, s in enumerate(first["slots"])]
        ready = all(done)
        names = [s["name"] for s, d in zip(first["slots"], done) if not d]
        label = label_of(first.get("action"))
        summary = (f"{label} approved - ready to complete" if ready else
                   f"{label} pending {sum(done)}/{len(done)}: waiting on " + ", ".join(names))
        task = Task(batch_id, first.get("action", RELEASE), [(m.pn, m.name, first.get("revision", "")) for m in members],
                    first.get("requested_by", ""), first.get("requested_at", ""), summary, slots, ready,
                    me is not None and first.get("requested_by_id") == me.id, first.get("reason", ""),
                    first.get("template_name", ""))
        if me is not None:
            task.can_sign = any(open_slots(p, me.id) for p in pendings)
            if not task.can_sign:
                task.why_not_sign = may_sign(first, me)[1]
            task.can_reject = any(_is_signer(p, me) for p in pendings) or _is_admin(me)
            task.can_complete = ready
            task.can_withdraw = task.mine or _is_admin(me)
            task.can_override = _is_admin(me)
            task.can_reassign = (task.mine or _is_admin(me)) and not ready
        tasks.append(task)
    tasks.sort(key=lambda t: (not (t.can_sign or (t.ready and t.mine)), t.requested_at))
    return tasks


def count_for_me(tasks):
    """How many tasks need you: sign-offs you can give, and your own approved requests waiting to be completed."""
    return sum(1 for t in tasks if t.can_sign or (t.ready and t.mine))
