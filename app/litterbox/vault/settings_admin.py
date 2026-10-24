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
    toolbox             the rule for SolidWorks Toolbox parts (core/toolbox_rules.py): "" (no check), "none" or
                        "team". A rule makes the vault need Litterbox 0.6.0, since older ones don't check it
Only an Admin or the Owner may change them (the permission is "manage_settings"); everyone then gets the new
values the next time they get the latest. Projects are changed through the same file, in project_admin.py.

    vault_settings.edit(repo, commit_style="per_batch", release_rule="block", assembly_variant_start=600)
"""

from pathlib import Path

from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.records.error_conversion import converts_errors
from litterbox.team import team_permissions
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.vault import shared_files


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


def change_file(repo, change, check=None):
    """Lock the settings file, get the latest, make the change (change() edits the file and returns the commit
    message), commit and upload. If anything fails the file is put back. True if the file changed. `check()` raises
    if the user may not make this change (default: only an Admin or the Owner, "manage_settings")."""
    repository.validate_repo(repo)
    if check is None:
        team_permissions.require(repo, "manage_settings")
    else:
        check()
    path = Path(repo) / layout.CONFIG_PATH

    def make_change():
        before = path.read_bytes() if path.is_file() else None
        try:
            message = change()
        except config.ConfigError as e:
            raise LitterboxError(str(e)) from None
        changed = (path.read_bytes() if path.is_file() else None) != before
        return ([layout.CONFIG_PATH] if changed else []), message, changed
    return shared_files.edit(repo, [layout.CONFIG_PATH], "the vault settings", make_change)
