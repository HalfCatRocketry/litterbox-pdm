"""
compatibility.py - may this copy of Litterbox open this vault? (Its format_version and
min_litterbox_version, against version.py.)
"""

from litterbox import layout
from litterbox import version
from litterbox.vault import config


def check_compatible(repo):
    """Raise ConfigError if this vault needs a newer Litterbox than this one (see version.py)."""
    data = config.load(repo)
    vault_format = data.get("format_version", 1)
    if isinstance(vault_format, bool) or not isinstance(vault_format, int) or vault_format < 1:
        raise config.ConfigError(f"format_version in {layout.CONFIG_PATH} must be a whole number, 1 or higher.")
    if vault_format > version.VAULT_FORMAT:
        raise config.ConfigError(
            f"This vault was set up by a newer Litterbox (vault format {vault_format}; this copy only understands "
            f"up to {version.VAULT_FORMAT}). Update Litterbox to open it. You have {version.VERSION}.")
    wanted = data.get("min_litterbox_version")
    if wanted not in (None, ""):
        try:
            too_old = version.parse(wanted) > version.parse(version.VERSION)
        except ValueError:
            raise config.ConfigError(f"min_litterbox_version in {layout.CONFIG_PATH} should look like 0.1.0.")
        if too_old:
            raise config.ConfigError(f"This vault needs Litterbox {wanted} or newer. You have {version.VERSION}. "
                              "Update Litterbox to continue.")
