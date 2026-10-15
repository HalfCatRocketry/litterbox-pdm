"""
workflow_store.py - reading and saving .litterbox/workflows.yaml (under a lock, with a pull before and a
push after), and which templates an action has.
"""

from pathlib import Path

import yaml

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import team_identity
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.vault import config_write
from litterbox.workflows import workflow_templates


def load(repo):
    """The vault's templates as {action: {name: Template}}. No file means no workflows."""
    path = Path(repo) / layout.WORKFLOWS_FILE
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise workflow_templates.WorkflowError(f"Could not read {layout.WORKFLOWS_FILE}: {e}")
    if data in (None, ""):
        return {}
    flows = data.get("workflows") if isinstance(data, dict) else None
    if flows in (None, ""):
        return {}
    if not isinstance(flows, dict):
        raise workflow_templates.WorkflowError(f"{layout.WORKFLOWS_FILE} should contain 'workflows:' followed by the actions.")
    templates = {}
    for action, body in flows.items():
        if not isinstance(body, dict) or "signoffs" in body:
            raise workflow_templates.WorkflowError(f"{layout.WORKFLOWS_FILE} is in the format of Litterbox 0.2. Delete the file (or the "
                                f"'{action}' part) and set the workflows up again in Team... > Workflows.")
        templates[str(action)] = {str(name): workflow_templates.Template.from_dict(str(action), name, t) for name, t in body.items()}
    workflow_templates.validate(templates)
    return templates


def save(repo, templates):
    path = Path(repo) / layout.WORKFLOWS_FILE
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


@converts_errors
def edit_templates(repo, change, message):
    """Change the workflow file for everyone: lock it, get the latest, `change(templates, directory)`, check,
    commit, push, unlock. If anything fails the file is put back. Admins only. Returns what change() returns."""
    repository.validate_repo(repo)
    identity = team_permissions.require(repo, "manage_workflows")
    if identity.state != team_identity.OK:
        raise workflow_templates.WorkflowError("Set up the team first (Team... > Set Up Team): workflows are about people's roles.")
    rel = layout.WORKFLOWS_FILE
    config_rel = f"{layout.CONFIG_DIR}/{layout.CONFIG_FILE}"
    existed = repository.in_index(repo, rel)
    config_tracked = repository.in_index(repo, config_rel)
    config_before = (Path(repo) / config_rel).read_bytes() if (Path(repo) / config_rel).is_file() else None
    if existed:
        lfs_locks.lock(repo, rel, "the workflows file")
    committed, result = False, None
    try:
        remote.pull(repo)
        templates = load(repo)
        directory = team_store.load(repo)
        result = change(templates, directory)
        workflow_templates.validate(templates, directory)
        save(repo, templates)
        paths = [rel]
        if templates:
            # Older versions don't know about pending requests and would let a part slip past its sign-offs, so
            # the vault now asks everyone to update before working in it.
            config_write.stamp(repo, min_version=workflow_templates.MIN_VERSION)
            paths.append(config_rel)
        runner.run(["git", "add", "--"] + paths, repo)
        runner.run(["git", "commit", "-m", message, "--"] + paths, repo)
        committed = True
        guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            if config_tracked:
                runner.run(["git", "restore", "--staged", "--worktree", "--", config_rel], repo)
            else:
                runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", config_rel], repo, quiet=True)
                try:
                    if config_before is None:
                        (Path(repo) / config_rel).unlink()
                    else:
                        (Path(repo) / config_rel).write_bytes(config_before)       # an untracked file of theirs
                except OSError:
                    pass
            if existed:
                runner.run(["git", "restore", "--staged", "--worktree", "--", rel], repo)
            else:
                runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", rel], repo, quiet=True)
                try:
                    (Path(repo) / rel).unlink()
                except OSError:
                    pass
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {rel}: {e}")
        if existed:
            lfs_locks.force_unlock_quietly(repo, [rel])
        raise
    if existed:
        failed = lfs_locks.unlock_mine(repo, [rel])
        if failed:
            raise LitterboxError(lfs_locks.unlock_failure_message(failed))
    return result
