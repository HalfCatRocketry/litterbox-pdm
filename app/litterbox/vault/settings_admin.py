"""
vault_settings.py - changing the vault's shared settings (.litterbox/config.yaml) from the program.

The settings here:
    commit_style        "per_part" (default) or "per_batch": one commit per part or one for the whole batch when
                        Check In / Save Progress is done on several parts at once
    release_rule        "warn" (default), "block" or "off": what a release does when the assembly uses parts that
                        are out of date or not released
    require_signatures  True or False (default): refuse uploads of commits not signed by a key on the team list
Only an Admin or the Owner may change them (the permission is "manage_settings"); everyone then gets the new
values the next time they get the latest.

    vault_settings.edit(repo, commit_style="per_batch", release_rule="block")
"""

from pathlib import Path

from litterbox.vault import config
from litterbox.parts import engine as eng
from litterbox.team import people
from litterbox.errors import LitterboxError
from litterbox.records.error_conversion import converts_errors
from litterbox import diagnostics

CONFIG_REL = f"{config.CONFIG_DIR}/{config.CONFIG_FILE}"


@converts_errors
def edit(repo, **values):
    """Change the settings given (see config.set_values), commit and upload the change. If anything fails the file
    is put back. Returns True if something changed, False if the vault already had those values."""
    eng.validate_repo(repo)
    people.require(repo, "manage_settings")
    path = Path(repo) / CONFIG_REL
    tracked = people._tracked(repo, CONFIG_REL)
    before = path.read_bytes() if path.is_file() else None
    if tracked:
        eng._lock(repo, CONFIG_REL, "the vault settings")
    committed = False
    try:
        eng._pull(repo)
        before = path.read_bytes() if path.is_file() else None
        try:
            config.set_values(repo, **values)
        except config.ConfigError as e:
            raise LitterboxError(str(e)) from None
        after = path.read_bytes() if path.is_file() else None
        if after == before:
            changed = False
        else:
            changed = True
            names = ", ".join(f"{key} = {value}" for key, value in values.items())
            eng.run(["git", "add", "--", CONFIG_REL], repo)
            eng.run(["git", "commit", "-m", f"Vault settings: {names}", "--", CONFIG_REL], repo)
            committed = True
            eng._push_with_retry(repo)
    except BaseException:
        try:
            if committed:
                eng.run(["git", "reset", "--soft", "HEAD~1"], repo)
            if tracked:
                eng.run(["git", "restore", "--staged", "--worktree", "--", CONFIG_REL], repo)
            else:
                eng.run(["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", CONFIG_REL], repo, quiet=True)
                if before is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(before)
        except (LitterboxError, OSError) as e:
            diagnostics.LOG(f"WARNING: could not fully undo the change to {CONFIG_REL}: {e}")
        if tracked:
            eng._force_unlock_quietly(repo, [CONFIG_REL])
        raise
    if tracked:
        failed = eng._unlock_mine(repo, [CONFIG_REL])
        if failed:
            raise LitterboxError(eng._unlock_failure_message(failed))
    return changed
