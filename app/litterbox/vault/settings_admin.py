"""
settings_admin.py - changing the vault's shared settings (.litterbox/config.yaml) from the program.

The settings here:
    commit_style        "per_part" (default) or "per_batch": one commit per part or one for the whole batch when
                        Check In / Save Progress is done on several parts at once
    release_rule        "warn" (default), "block" or "off": what a release does when the assembly uses parts that
                        are out of date or not released
    require_signatures  True or False (default): refuse uploads of commits not signed by a key on the team list
    org_name            the org's full name; only the Owner may change it (the permission is "rename_org")
    solidworks_version  the SolidWorks everyone works in, as a year (2024), or None for no check. Setting it makes
                        the vault need this Litterbox or newer, since older ones don't check it
    currency            the team's currency code (USD), or None: costs are shown with its symbol
Only an Admin or the Owner may change them (the permission is "manage_settings"); everyone then gets the new
values the next time they get the latest. Projects are changed through the same file, in project_admin.py.

    vault_settings.edit(repo, commit_style="per_batch", release_rule="block", assembly_variant_start=600)
"""

from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.git import remote
from litterbox.git import repository
from litterbox.git import runner
from litterbox.records.error_conversion import converts_errors
from litterbox.team import guarded_push
from litterbox.team import team_permissions
from litterbox.vault import config
from litterbox.vault import config_write

CONFIG_REL = f"{layout.CONFIG_DIR}/{layout.CONFIG_FILE}"


@converts_errors
def edit(repo, **values):
    """Change the settings given (see config_write.set_values), commit and upload the change. If anything fails the file
    is put back. Returns True if something changed, False if the vault already had those values."""
    if "org_name" in values:
        team_permissions.require(repo, "rename_org")

    def change():
        config_write.set_values(repo, **values)
        return "Vault settings: " + ", ".join(f"{key} = {value}" for key, value in values.items())
    return change_file(repo, change)


def change_file(repo, change):
    """Lock the settings file, get the latest, make the change (change() edits the file and returns the commit
    message), commit and upload. If anything fails the file is put back. True if the file changed."""
    repository.validate_repo(repo)
    team_permissions.require(repo, "manage_settings")
    path = Path(repo) / CONFIG_REL
    tracked = repository.in_index(repo, CONFIG_REL)
    before = path.read_bytes() if path.is_file() else None
    if tracked:
        lfs_locks.lock(repo, CONFIG_REL, "the vault settings")
    committed = False
    try:
        remote.pull(repo)
        before = path.read_bytes() if path.is_file() else None
        try:
            message = change()
        except config.ConfigError as e:
            raise LitterboxError(str(e)) from None
        after = path.read_bytes() if path.is_file() else None
        if after == before:
            changed = False
        else:
            changed = True
            runner.run(["git", "add", "--", CONFIG_REL], repo)
            runner.run(["git", "commit", "-m", message, "--", CONFIG_REL], repo)
            committed = True
            guarded_push.push(repo)
    except BaseException:
        try:
            if committed:
                runner.run(["git", "reset", "--soft", "HEAD~1"], repo)
            if tracked:
                runner.run(["git", "restore", "--staged", "--worktree", "--", CONFIG_REL], repo)
            else:
                runner.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", CONFIG_REL], repo, quiet=True)
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(before)
        except (LitterboxError, OSError) as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {CONFIG_REL}: {e}")
        if tracked:
            lfs_locks.force_unlock_quietly(repo, [CONFIG_REL])
        raise
    if tracked:
        failed = lfs_locks.unlock_mine(repo, [CONFIG_REL])
        if failed:
            raise LitterboxError(lfs_locks.unlock_failure_message(failed))
    return changed
