"""
vault_settings.py - changing the vault's shared settings (.litterbox/config.yaml) from the program.

Today there is one setting here, `commit_style`: whether Check In / Save Progress on several parts at once make one
commit per part (the default) or one commit for the whole batch (faster). Only an Admin or the Owner may change it
(the permission is "manage_settings"); everyone then gets the new value the next time they get the latest.

    vault_settings.edit(repo, commit_style="per_batch")
"""

from pathlib import Path

import config
import litterbox_engine as eng
import people

CONFIG_REL = f"{config.CONFIG_DIR}/{config.CONFIG_FILE}"


@eng._converts_errors
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
            raise eng.LitterboxError(str(e)) from None
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
        except (eng.LitterboxError, OSError) as e:
            eng.LOG(f"WARNING: could not fully undo the change to {CONFIG_REL}: {e}")
        if tracked:
            eng._force_unlock_quietly(repo, [CONFIG_REL])
        raise
    if tracked:
        failed = eng._unlock_mine(repo, [CONFIG_REL])
        if failed:
            raise eng.LitterboxError(eng._unlock_failure_message(failed))
    return changed
