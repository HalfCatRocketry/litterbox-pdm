"""
workflow_store.py - reading and saving .litterbox/workflows.yaml (under a lock, with a pull before and a
push after), and which templates an action has.
"""

from pathlib import Path

import yaml

from litterbox import layout
from litterbox import version
from litterbox.git import repository
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_identity
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.util import fast_yaml
from litterbox.vault import config_write
from litterbox.vault import shared_files
from litterbox.workflows import workflow_templates


def load(repo):
    """The vault's templates as {action: {name: Template}}. No file means no workflows."""
    path = Path(repo) / layout.WORKFLOWS_FILE
    if not path.is_file():
        return {}
    try:
        data = fast_yaml.safe_load(path.read_text(encoding="utf-8"))
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
                                f"'{action}' part) and set the workflows up again in Team > Part Workflows... and Doc Workflows....")
        templates[str(action)] = {str(name): workflow_templates.Template.from_dict(str(action), name, t) for name, t in body.items()}
    workflow_templates.validate(templates)
    return templates


def _other_sections(path):
    """What the file holds besides 'workflows' (written by a newer Litterbox), so saving keeps it."""
    try:
        data = fast_yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, yaml.YAMLError):
        return {}
    return {k: v for k, v in data.items() if k != "workflows"} if isinstance(data, dict) else {}


def save(repo, templates):
    path = Path(repo) / layout.WORKFLOWS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"workflows": {action: {name: t.to_dict() for name, t in named.items()}
                          for action, named in sorted(templates.items()) if named}}
    body.update(_other_sections(path))
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
        raise workflow_templates.WorkflowError("Set up the team first (Team > Set Up Team): workflows are about people's roles.")

    def make_change():
        templates = load(repo)
        directory = team_store.load(repo)
        result = change(templates, directory)
        workflow_templates.validate(templates, directory)
        save(repo, templates)
        paths = [layout.WORKFLOWS_FILE]
        if templates:
            # Older versions don't know about pending requests and would let a part slip past its sign-offs, so
            # the vault now asks everyone to update before working in it.
            config_write.stamp(repo, min_version=workflow_templates.min_version_for(templates, version.release()))
            paths.append(layout.CONFIG_PATH)
        return paths, message, result
    return shared_files.edit(repo, [layout.WORKFLOWS_FILE, layout.CONFIG_PATH], "the workflows file", make_change)
