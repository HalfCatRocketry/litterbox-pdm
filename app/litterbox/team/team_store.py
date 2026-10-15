"""
team_store.py - reading and saving .litterbox/people.yaml (and the allowed_signers file made from it),
and the check before every push that the vault's latest team list still lets you upload.
"""

import os
from pathlib import Path

import yaml

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_permissions
from litterbox.vault import config


def load(repo):
    """The vault's Directory, or None when the vault has no people file yet (legacy mode)."""
    path = Path(repo) / layout.PEOPLE_FILE
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
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
    repository.validate_repo(repo)
    identity = team_permissions.require(repo, action)
    if identity.state == team_identity.LEGACY:
        raise team_model.PeopleError("The team has not been set up yet. Use Set Up Team first.")
    rel = layout.PEOPLE_FILE
    lfs_locks.lock(repo, rel, "the people file")
    committed, added_signers, result = False, False, None
    signers_before_tracked = repository.in_index(repo, layout.ALLOWED_SIGNERS_FILE)
    try:
        remote.pull(repo)
        directory = load(repo)
        actor = directory.find_by_host_name(identity.host_name)
        if actor is None or not actor.active:
            raise team_model.PeopleError("Your access changed while you were working. Run Get Latest.")
        result = change(directory, actor)
        save(repo, directory)
        paths = [rel]
        signers = _write_allowed_signers(repo, directory)
        if signers:
            paths.append(signers)
            added_signers = not signers_before_tracked
        runner.run(["git", "add", "--"] + paths, repo)
        runner.run(["git", "commit", "-m", message, "--"] + paths, repo)
        committed = True
        remote.push_with_retry(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            runner.run(["git", "restore", "--staged", "--worktree", "--", rel], repo)
            if signers_before_tracked:
                runner.run(["git", "restore", "--staged", "--worktree", "--", layout.ALLOWED_SIGNERS_FILE], repo)
            elif added_signers or (Path(repo) / layout.ALLOWED_SIGNERS_FILE).exists():
                runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", layout.ALLOWED_SIGNERS_FILE], repo,
                        quiet=True)
                try:
                    (Path(repo) / layout.ALLOWED_SIGNERS_FILE).unlink()
                except OSError:
                    pass
        except LitterboxError as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {rel}: {e}")
        lfs_locks.force_unlock_quietly(repo, [rel])
        raise
    failed = lfs_locks.unlock_mine(repo, [rel])
    if failed:
        raise LitterboxError(lfs_locks.unlock_failure_message(failed))
    return result


def check_before_push(repo):
    """Before a push: get the vault's latest people file and make sure it still lets this user push.

    This is how "you were switched off while you were away" is caught: the commits you made offline are
    not uploaded, and you are told why. A vault with no people file is not checked.
    """
    if load(repo) is None:
        return
    try:
        runner.run(["git", "fetch"], repo, quiet=True)
        text = runner.run(["git", "show", f"@{{u}}:{layout.PEOPLE_FILE}"], repo, quiet=True)
    except LitterboxError:
        return                                  # offline, or the vault has no people file yet: git will say if the push fails
    try:
        upstream = team_model.from_dict(yaml.safe_load(text) or {})
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
