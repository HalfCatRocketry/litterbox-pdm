"""
workflow.py - sign-offs before a part is released.

An Admin can say "a release needs sign-offs". After that, pressing Release no longer releases: it asks.
People who hold the required roles approve (or reject), and when everyone needed has approved, the part
is released. Version 1 covers RELEASE only, with every sign-off in parallel (any order).

THE TEMPLATE   .litterbox/workflows.yaml, shared through Git like the team file. Admins edit it.

    workflows:
      release:
        allow_self_signoff: true        the person who asked may also sign (default true)
        signoffs:
        - role: Quality                 anyone with this role
          count: 1                      how many different people must sign (default 1)
        - role: Responsible Engineer

    No release template = Release works as it always did.

THE REQUEST    While a request waits, it lives in the part's record under `pending`:
    action, revision, requested_by (+ _id, _at), the template AS IT WAS when asked (so editing the template
    later changes nothing already in flight), the hash of every CAD file, and each sign-off so far.
    A part with a pending request can't be checked out, so what gets approved is what gets released.

THE STEPS      request_release -> sign_off (any number of people) -> complete_release
    The last sign-off completes the release straight away. If that can't happen (offline, behind the
    vault, something blocks it) the sign-off is still saved and the part shows "approved, ready": the
    requester, or anyone, presses Release again to finish.
    reject        a role holder (or Admin) sends it back with a comment. The part is in work again.
    withdraw      the requester (or Admin) cancels the request.
    override_release   an Admin releases without the sign-offs. A reason is required and it is recorded
                  as an override.

THE TRAIL      A finished release adds an entry to the record's `approvals` list: who requested, who signed
    (with roles and times), the template, the file hashes, and any override with its reason. Every step also
    appears in the part's history.

Everything here that changes a record uses the same lock, pull, change, commit, push, unlock routine as the
rest of Litterbox (litterbox_engine._edit_record).
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import config
import litterbox_engine as eng
import people
import registry

WORKFLOWS_FILE = ".litterbox/workflows.yaml"
RELEASE = "release"
ACTIONS = (RELEASE,)                                  # the actions that can have a template (more later)
ACTION_LABEL = {RELEASE: "Release"}
MAX_COUNT = 20
MIN_VERSION = "0.2.0"      # the first Litterbox that understands pending requests; a vault with a workflow requires it


class WorkflowError(eng.LitterboxError):
    """A workflow file or step is wrong, or something isn't allowed. The message is safe to show."""


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@dataclass
class Step:
    role: str
    count: int = 1


@dataclass
class Template:
    action: str
    steps: list = field(default_factory=list)
    allow_self_signoff: bool = True

    def to_dict(self):
        return {"allow_self_signoff": self.allow_self_signoff,
                "signoffs": [{"role": s.role, "count": s.count} for s in self.steps]}

    @classmethod
    def from_dict(cls, action, data):
        if not isinstance(data, dict):
            raise WorkflowError(f"The {action} workflow should list its sign-offs.")
        allow = data.get("allow_self_signoff", True)
        if not isinstance(allow, bool):
            raise WorkflowError(f"allow_self_signoff in the {action} workflow must be true or false.")
        steps = []
        for item in data.get("signoffs") or []:
            if not isinstance(item, dict) or not str(item.get("role", "")).strip():
                raise WorkflowError(f"Every sign-off in the {action} workflow needs a role.")
            count = item.get("count", 1)
            steps.append(Step(" ".join(str(item["role"]).split()), count))
        return cls(action, steps, allow)


def validate(templates, directory=None):
    """Raise WorkflowError if a template is unusable. With the team directory, roles must be ones the org has
    (their spelling is tidied to match). `templates` is {action: Template}."""
    for action, template in templates.items():
        label = ACTION_LABEL.get(action)
        if label is None:
            raise WorkflowError(f"'{action}' can't have a workflow yet. Only {', '.join(ACTIONS)} can.")
        if not template.steps:
            raise WorkflowError(f"The {label} workflow needs at least one sign-off. Remove the workflow instead "
                                "if releases shouldn't need any.")
        seen = set()
        for step in template.steps:
            if isinstance(step.count, bool) or not isinstance(step.count, int) or not (1 <= step.count <= MAX_COUNT):
                raise WorkflowError(f"How many people must sign as {step.role} must be a whole number from 1 "
                                    f"to {MAX_COUNT}.")
            if step.role.lower() in seen:
                raise WorkflowError(f"{step.role} appears twice in the {label} workflow. Use one sign-off with a "
                                    "higher number of people instead.")
            seen.add(step.role.lower())
            if directory is not None:
                match = next((r for r in directory.roles if r.lower() == step.role.lower()), None)
                if match is None:
                    raise WorkflowError(f"'{step.role}' isn't one of this org's roles. Add it in Team... > Roles "
                                        "first.")
                step.role = match


def load(repo):
    """The vault's templates as {action: Template}. No file means no workflows."""
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
    templates = {str(action): Template.from_dict(str(action), body) for action, body in flows.items()}
    validate(templates)
    return templates


def save(repo, templates):
    path = Path(repo) / WORKFLOWS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"workflows": {action: t.to_dict() for action, t in sorted(templates.items())}}
    tmp = path.with_name(".tmp-workflows.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(body, f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)


def template_for(repo, action):
    """The template for this action, or None if releases etc. need no sign-offs."""
    return load(repo).get(action)


def role_warnings(template, directory):
    """Sentences about roles that nobody active holds enough people for (the part would wait for an override)."""
    warnings = []
    for step in template.steps:
        holders = _active_holders(directory, step.role)
        if len(holders) < step.count:
            who = f"only {len(holders)} active {'person has' if len(holders) == 1 else 'people have'} the role" \
                if holders else "nobody active has the role"
            warnings.append(f"{step.role}: {step.count} sign-off{'s' if step.count != 1 else ''} needed but {who}.")
    return warnings


def _active_holders(directory, role):
    return [p for p in directory.people if p.active and role.lower() in (r.lower() for r in p.roles)]


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


def set_template(templates, action, steps, allow_self_signoff=True):
    """Put a template in `templates` (steps are (role, count) pairs). For use inside edit_templates()."""
    templates[action] = Template(action, [Step(" ".join(str(r).split()), c) for r, c in steps], allow_self_signoff)


def remove_template(templates, action):
    templates.pop(action, None)


# ---------------------------------------------------------------------------
# A pending request: how far along is it?
# ---------------------------------------------------------------------------

@dataclass
class StepProgress:
    role: str
    need: int
    have: int
    names: list

    @property
    def done(self):
        return self.have >= self.need


def _roles_of(entry):
    return [str(r).lower() for r in entry.get("roles", [])]


def progress(pending):
    """A StepProgress for each sign-off the request needs."""
    steps = []
    for item in pending["template"].get("signoffs", []):
        role, need = item["role"], int(item.get("count", 1))
        seen, names = set(), []
        for entry in pending["signoffs"]:
            who = entry.get("id") or entry.get("by")
            if role.lower() in _roles_of(entry) and who not in seen:
                seen.add(who)
                names.append(entry.get("by", ""))
        steps.append(StepProgress(role, need, len(names), names))
    return steps


def is_complete(pending):
    return all(step.done for step in progress(pending))


def describe_pending(pending):
    """Short text for the part list: 'Release pending: Quality 0/1, Responsible Engineer 1/1'."""
    steps = progress(pending)
    if all(s.done for s in steps):
        return "Release approved - ready to complete"
    return "Release pending: " + ", ".join(f"{s.role} {s.have}/{s.need}" for s in steps)


def waiting_on(pending):
    """Sentences for what is still missing, e.g. ['Quality (0 of 1)']."""
    return [f"{s.role} ({s.have} of {s.need})" for s in progress(pending) if not s.done]


def open_roles(pending, person):
    """The roles this person could still sign for on this request (in the template's spelling)."""
    held = {r.lower() for r in person.roles}
    signed = {r for e in pending["signoffs"] if (e.get("id") or e.get("by")) == person.id for r in _roles_of(e)}
    return [s.role for s in progress(pending) if not s.done and s.role.lower() in held and s.role.lower() not in signed]


def may_sign(pending, person):
    """(True, '') or (False, why not) for this person signing this request."""
    if pending["template"].get("allow_self_signoff", True) is False and pending.get("requested_by_id") == person.id:
        return False, "This vault doesn't let you sign off your own request."
    if not open_roles(pending, person):
        if is_complete(pending):
            return False, "Everyone needed has already signed."
        return False, "You don't hold a role that is still needed, or you have already signed for it."
    return True, ""


def _is_admin(person):
    return person.access in (people.OWNER, people.ADMIN)


def _holds_a_template_role(pending, person):
    held = {r.lower() for r in person.roles}
    return any(item["role"].lower() in held for item in pending["template"].get("signoffs", []))


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
    """The current user as a team member. Workflows are about roles, so a vault with no team can't use them."""
    identity = people.require(repo, action)
    if identity.state != people.OK or identity.person is None:
        raise WorkflowError("Set up the team first (Team... > Set Up Team): sign-offs are done by people with roles.")
    return identity.person


def _pending_of(record, action=RELEASE):
    if not record.pending or record.pending.get("action") != action:
        raise WorkflowError(f"{record.pn} has no {ACTION_LABEL[action].lower()} request waiting for sign-offs. "
                            "Run Get Latest in case it was already dealt with.")
    if record.pending.get("revision") != record.revision:
        raise WorkflowError(f"The request for {record.pn} is for Rev {record.pending.get('revision')}, which is no "
                            "longer the working revision. Withdraw it.")
    return record.pending


def _check_files_unchanged(repo, pending):
    now = file_hashes(repo, list(pending.get("files", {})))
    for rel, digest in pending.get("files", {}).items():
        if now.get(rel) != digest:
            raise WorkflowError(f"{rel} is different from the file the sign-offs were asked for. Withdraw the "
                                "request and ask again. If you think your copy is behind, run Get Latest.")


@eng._converts_errors
def request_release(repo, pn):
    """Ask for sign-offs to release a part. Checks everything a normal release checks, then records the request.
    The part can't be checked out until the request ends. Returns the text describing where it stands."""
    pn = eng._as_pn(pn)
    me = _me(repo, "release")
    template = template_for(repo, RELEASE)
    if template is None:
        raise WorkflowError("Releases in this vault don't need sign-offs. Use Release normally.")
    plan = eng.release_plan(repo, pn)
    if not plan.ok:
        raise eng.LitterboxError(f"{pn} can't be released yet:\n- " + "\n- ".join(plan.problems))
    hashes = file_hashes(repo, plan.files)
    out = []

    def edit(record, user):
        if record.status != registry.STATUS_IN_WORK or record.cots:
            raise registry.RegistryError(f"Cannot release {record.pn}: its status is '{record.status}'.")
        if record.pending:
            raise registry.RegistryError(f"{record.pn} already has a request waiting for sign-offs.")
        record.pending = {
            "action": RELEASE, "revision": record.revision, "requested_by": user, "requested_by_id": me.id,
            "requested_at": registry.now_utc(), "template": template.to_dict(), "files": dict(hashes),
            "signoffs": [],
        }
        registry.add_event(record, registry.EVENT_RELEASE_REQUESTED, user,
                           waiting_on=waiting_on(record.pending), files=list(plan.files))
        out.append(describe_pending(record.pending))

    eng._edit_record(repo, pn, "release", edit, f"{pn}: Release requested")
    return out[0]


@dataclass
class SignResult:
    completed: bool = False         # the release went through
    error: str = ""                 # why it didn't complete although everyone has signed
    summary: str = ""               # where the request stands


@eng._converts_errors
def sign_off(repo, pn, comment=""):
    """Approve a pending release as the roles you hold that are still needed. If yours is the last sign-off the
    release is completed straight away; if that fails the sign-off is still saved (see SignResult.error)."""
    pn = eng._as_pn(pn)
    me = _me(repo, "signoff")
    comment = " ".join((comment or "").split())
    out = []

    def edit(record, user):
        pending = _pending_of(record)
        ok, why = may_sign(pending, me)
        if not ok:
            raise registry.RegistryError(why)
        _check_files_unchanged(repo, pending)
        roles = open_roles(pending, me)
        pending["signoffs"].append({"by": user, "id": me.id, "roles": roles, "at": registry.now_utc(),
                                    **({"comment": comment} if comment else {})})
        registry.add_event(record, registry.EVENT_RELEASE_SIGNED, user, roles=roles, comment=comment or None,
                           waiting_on=waiting_on(pending) or None)
        out.append(is_complete(pending))

    eng._edit_record(repo, pn, "signoff", edit, f"{pn}: Release signed off")
    result = SignResult(summary="")
    if out[0]:
        try:
            complete_release(repo, pn)
            result.completed = True
        except eng.LitterboxError as e:
            result.error = str(e)
    record = registry.load(repo, pn)
    result.summary = describe_pending(record.pending) if record.pending else f"Released Rev {record.released_revision}"
    return result


def _approval_entry(pending, completed_by, override=None, files=None):
    entry = {"action": RELEASE, "revision": pending.get("revision") if pending else None}
    if pending:
        entry.update({"requested_by": pending.get("requested_by"), "requested_at": pending.get("requested_at"),
                      "template": pending.get("template"), "signoffs": list(pending.get("signoffs", [])),
                      "files": dict(pending.get("files", {}))})
    else:
        entry.update({"signoffs": [], "files": dict(files or {})})
    entry["completed_by"] = completed_by
    entry["completed_at"] = registry.now_utc()
    if override:
        entry["override"] = override
    return {k: v for k, v in entry.items() if v is not None}


def _finish(repo, pn, action, override_reason=None):
    """Release the part now. Shared by complete_release and override_release."""
    pn = eng._as_pn(pn)
    plan = eng.release_plan(repo, pn, allow_pending=True)
    if not plan.ok:
        raise eng.LitterboxError(f"{pn} can't be released yet:\n- " + "\n- ".join(plan.problems))

    def edit(record, user):
        pending = record.pending or None
        if override_reason is None:
            pending = _pending_of(record)
            if not is_complete(pending):
                raise registry.RegistryError("Still waiting for: " + ", ".join(waiting_on(pending)) + ".")
            _check_files_unchanged(repo, pending)
        signed = [e.get("by") for e in (pending or {}).get("signoffs", [])]
        details = {"signoffs": signed or None}
        override = None
        if override_reason is not None:
            missing = waiting_on(pending) if pending else [s.role for s in template_for(repo, RELEASE).steps]
            override = {"by": user, "reason": override_reason, "missing": missing}
            details.update(override=True, reason=override_reason)
        files = file_hashes(repo, plan.files) if not pending else None
        registry.mark_released(record, user, plan.files, **details)
        record.approvals.append(_approval_entry(pending, user, override, files))
        record.pending = {}

    message = f"{pn}: Released" + (" (Admin override)" if override_reason is not None else " after sign-offs")
    eng._edit_record(repo, pn, action, edit, message)
    return plan.files


@eng._converts_errors
def complete_release(repo, pn):
    """Release a part whose request has every sign-off. Returns the files that were frozen."""
    _me(repo, "release")
    return _finish(repo, pn, "release")


@eng._converts_errors
def override_release(repo, pn, reason):
    """Admins only: release without the sign-offs. A reason is required and is recorded as an override."""
    _me(repo, "override_release")
    reason = " ".join((reason or "").split())
    if not reason:
        raise WorkflowError("A reason is required to release without sign-offs.")
    if template_for(repo, RELEASE) is None:
        raise WorkflowError("Releases in this vault don't need sign-offs. Use Release normally.")
    return _finish(repo, pn, "override_release", override_reason=reason)


@eng._converts_errors
def reject(repo, pn, comment):
    """Send a pending release back. Anyone holding a role the workflow names (or an Admin) may; a comment is
    required. The part is in work again and can be checked out."""
    pn = eng._as_pn(pn)
    me = _me(repo, "signoff")
    comment = " ".join((comment or "").split())
    if not comment:
        raise WorkflowError("Say why you are rejecting it, so the person who asked knows what to fix.")

    def edit(record, user):
        pending = _pending_of(record)
        if not (_holds_a_template_role(pending, me) or _is_admin(me)):
            raise registry.RegistryError("Only people holding a role this workflow needs (or an Admin) can reject it.")
        registry.add_event(record, registry.EVENT_RELEASE_REJECTED, user, reason=comment,
                           requested_by=pending.get("requested_by"),
                           signed=[e.get("by") for e in pending["signoffs"]] or None)
        record.pending = {}

    eng._edit_record(repo, pn, "signoff", edit, f"{pn}: Release rejected - {comment}")


@eng._converts_errors
def withdraw(repo, pn, reason=""):
    """Cancel a pending release. The person who asked, or an Admin, may."""
    pn = eng._as_pn(pn)
    me = _me(repo, "release")
    reason = " ".join((reason or "").split())

    def edit(record, user):
        pending = _pending_of(record)
        mine = pending.get("requested_by_id") == me.id
        if not (mine or _is_admin(me)):
            raise registry.RegistryError("Only the person who asked, or an Admin, can withdraw the request.")
        registry.add_event(record, registry.EVENT_RELEASE_WITHDRAWN, user, reason=reason or None,
                           requested_by=pending.get("requested_by"))
        record.pending = {}

    eng._edit_record(repo, pn, "release", edit, f"{pn}: Release request withdrawn")


# ---------------------------------------------------------------------------
# My Tasks
# ---------------------------------------------------------------------------

@dataclass
class Task:
    pn: object
    name: str
    revision: str
    requested_by: str
    requested_at: str
    summary: str
    ready: bool                     # every sign-off is in; waiting to be completed
    mine: bool                      # you asked for it
    can_sign: bool = False
    can_reject: bool = False
    can_complete: bool = False
    can_withdraw: bool = False
    can_override: bool = False
    why_not_sign: str = ""


def tasks_from_rows(rows, identity):
    """Everything waiting on a sign-off, from the part list's rows (PartStatus). With no team member identity
    the tasks are listed, but nothing can be done to them."""
    me = identity.person if identity.state == people.OK else None
    tasks = []
    for row in rows:
        pending = getattr(row, "pending", None)
        if not pending or pending.get("action") != RELEASE:
            continue
        ready = is_complete(pending)
        task = Task(row.pn, row.name, pending.get("revision", ""), pending.get("requested_by", ""),
                    pending.get("requested_at", ""), describe_pending(pending), ready,
                    me is not None and pending.get("requested_by_id") == me.id)
        if me is not None:
            task.can_sign, task.why_not_sign = may_sign(pending, me)
            task.can_reject = _holds_a_template_role(pending, me) or _is_admin(me)
            task.can_complete = ready
            task.can_withdraw = task.mine or _is_admin(me)
            task.can_override = _is_admin(me)
        tasks.append(task)
    tasks.sort(key=lambda t: (not (t.can_sign or (t.ready and t.mine)), t.requested_at))
    return tasks


def count_for_me(tasks):
    """How many tasks need you: sign-offs you can give, and your own approved requests waiting to be completed."""
    return sum(1 for t in tasks if t.can_sign or (t.ready and t.mine))
