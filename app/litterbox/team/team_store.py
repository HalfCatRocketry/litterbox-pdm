"""
team_store.py - reading and saving .litterbox/people.yaml (and the allowed_signers file made from it),
and the check before every push that the vault's latest team list still lets you upload.
"""

import os
from pathlib import Path

import yaml

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.git import runner
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_permissions
from litterbox.util import fast_yaml
from litterbox.vault import config


def load(repo):
    """The vault's Directory, or None when the vault has no people file yet (legacy mode)."""
    path = Path(repo) / layout.PEOPLE_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = fast_yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        raise team_model.PeopleError(f"Could not read {layout.PEOPLE_FILE}: {e}")
    return team_model.from_dict(data)


def dump(directory):
    return yaml.safe_dump(directory.to_dict(), sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=100)


def save(repo, directory):
    team_model.validate(directory)
    path = Path(repo) / layout.PEOPLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, 0o644)
    tmp = path.with_name(".tmp-people.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(directory))
    tmp.replace(path)


def allowed_signers_text(directory):
    """The file git uses to check signed commits: one line per signing key, named by the person's id."""
    lines = [f'{p.id} namespaces="git" {key}' for p in directory.people if p.active for key in p.signing_keys]
    return "\n".join(lines) + ("\n" if lines else "")


def _write_allowed_signers(repo, directory):
    text = allowed_signers_text(directory)
    path = Path(repo) / layout.ALLOWED_SIGNERS_FILE
    if not text and not path.exists():
        return None
    if path.exists():
        os.chmod(path, 0o644)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return layout.ALLOWED_SIGNERS_FILE


def edit_directory(repo, change, message, action="manage_people"):
    """Apply `change(directory, actor_person)` to the people file for everyone: lock it, get the latest,
    change it, commit, push, unlock. If anything fails the file is put back as it was.
    Returns whatever change() returns."""
    from litterbox.vault import shared_files          # it uploads through guarded_push, which needs this module
    repository.validate_repo(repo)
    identity = team_permissions.require(repo, action)
    if identity.state == team_identity.LEGACY:
        raise team_model.PeopleError("The team has not been set up yet. Use Set Up Team first.")

    def make_change():
        directory = load(repo)
        actor = directory.find_by_host_name(identity.host_name)
        if actor is None or not actor.active:
            raise team_model.PeopleError("Your access changed while you were working. Run Get Latest.")
        result = change(directory, actor)
        save(repo, directory)
        signers = _write_allowed_signers(repo, directory)
        return [layout.PEOPLE_FILE] + ([signers] if signers else []), message, result
    return shared_files.edit(repo, [layout.PEOPLE_FILE, layout.ALLOWED_SIGNERS_FILE], "the people file", make_change)


def check_before_push(repo, fetch=True):
    """Before a push: get the vault's latest people file and make sure it still lets this user push (and, if the
    vault requires it, that every commit to upload is signed by a key on the team list). fetch=False when a sync has
    just fetched (guarded_push does that).

    This is how "you were switched off while you were away" is caught: the commits you made offline are
    not uploaded, and you are told why. A vault with no people file is not checked.
    """
    if load(repo) is None:
        return
    try:
        if fetch:
            runner.run(["git", "fetch"], repo, quiet=True)
        text = runner.run(["git", "show", f"@{{u}}:{layout.PEOPLE_FILE}"], repo, quiet=True)
    except LitterboxError:
        return                                  # offline, or the vault has no people file yet: git will say if the push fails
    try:
        upstream = team_model.from_dict(fast_yaml.safe_load(text) or {})
    except (yaml.YAMLError, team_model.PeopleError):
        return
    host_name, _checked = team_identity.read_cache(repo)
    identity = team_identity.resolve(upstream, host_name)
    if identity.state in (team_identity.NOT_LISTED, team_identity.INACTIVE):
        raise team_model.PeopleError("Nothing was uploaded. " + identity.message().replace(
            "you can look but not change anything", "you can no longer upload changes")
            + "\nYour changes are still on your computer.")
    if config.get_require_signatures(repo):
        from litterbox.team import commit_signing as signing
        bad = signing.untrusted_unpushed(repo)
        if bad:
            lines = "\n".join(f"  {s.subject} - {s.description}" for s in bad[:8])
            raise team_model.PeopleError("Nothing was uploaded. This vault requires every commit to be signed by a key on "
                              f"the team list, and these are not:\n{lines}\n\nUse Signing... to turn signing on "
                              "and give an Admin your public key. Your changes are still on your computer.")
