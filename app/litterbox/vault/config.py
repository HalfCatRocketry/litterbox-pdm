"""
config.py - the vault's shared settings, read from .litterbox/config.yaml (inside the vault, so the whole
team uses the same ones):

    org: HCR              the org code that starts every part number
    start_number: 10001   the first part number to hand out (optional, default 1). Numbers count up from here to
                          the highest the digits allow, then start again at 1 and stop just below it
    pn_base_digits: 5     digits in the part number (HCR-10001-001), default 5
    pn_variant_digits: 3  digits in the variant number (HCR-10001-001), default 3
    format_version: 1     the layout of the vault's files (see version.py), default 1
    min_litterbox_version: 0.1.0   the oldest Litterbox allowed in this vault, default none
    commit_style, release_rule, require_signatures   see their get_ functions below

If the file doesn't exist yet, the org code is worked out from the part numbers already in the vault (as long as
they all use the same one). vault/create_vault.py writes the file for new vaults.

Writing the settings is in config_write.py; checking that this Litterbox may open the vault is in
compatibility.py. This is different from user/settings.py, which holds YOUR personal settings and lives outside
the vault.
"""

from pathlib import Path

import yaml

from litterbox import layout
from litterbox.core import part_number
from litterbox.core.part_number import PNError, check_org
from litterbox.records import record_store
from litterbox.vault import compatibility


class ConfigError(Exception):
    """Something is wrong with the vault's settings. The message is safe to show to a user."""


class NoOrgError(ConfigError):
    """The vault has no org code yet (no config file and no part numbers to infer it from)."""


def config_path(repo):
    return Path(repo) / layout.CONFIG_DIR / layout.CONFIG_FILE


def load(repo):
    """The vault's settings as a dict. A missing file is fine and gives {}."""
    path = config_path(repo)
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"Could not read {layout.CONFIG_DIR}/{layout.CONFIG_FILE}: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{layout.CONFIG_DIR}/{layout.CONFIG_FILE} should contain settings like 'org: HCR'.")
    return data


def get_org(repo):
    """The vault's org code, for example 'HCR'.

    From the config file if it has one, otherwise from the existing part numbers.
    """
    configured = load(repo).get("org")
    if configured not in (None, ""):
        try:
            return check_org(configured)
        except PNError as e:
            raise ConfigError(f"The org code in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} is not valid. {e}")

    orgs = sorted({pn.org for pn in record_store.list_pns(repo)})
    if len(orgs) == 1:
        return orgs[0]
    if not orgs:
        raise NoOrgError(
            "This vault doesn't have an org code yet. Create the file "
            f"{layout.CONFIG_DIR}/{layout.CONFIG_FILE} in the vault, containing a line like:\n  org: HCR")
    raise ConfigError(
        f"This vault has part numbers from several orgs ({', '.join(orgs)}), so Litterbox can't "
        f"tell which to use. Set one in {layout.CONFIG_DIR}/{layout.CONFIG_FILE}, for example:\n  org: {orgs[0]}")


def get_start_number(repo):
    """The first part number to hand out (default 1). Numbers count up from it, then round again from 1 (see pn.next_base)."""
    value = load(repo).get("start_number")
    if value in (None, ""):
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"start_number in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} must be a whole number, 1 or higher "
                          f"(for example 10001), not {value!r}.")
    return value


def explain_start_number(repo):
    """One sentence saying where the start number came from (or why it is the default 1). For the Import window."""
    path = config_path(repo)
    try:
        if not path.is_file():
            text = f"There is no settings file at {path}, so the start number is 1."
            others = [p for p in (Path(repo) / layout.CONFIG_DIR / "config.yml", Path(repo) / "config.yaml",
                                  Path(repo) / "config.yml") if p.is_file()]
            if others:
                text += f" (Litterbox does not read {others[0]}; the settings must be in {path}.)"
            return text
        data = load(repo)
    except ConfigError as e:
        return str(e)
    if data.get("start_number") not in (None, ""):
        return f"start_number is {data['start_number']} (from {path})."
    near = [str(k) for k in data if "start" in str(k).lower()]
    hint = f" It has a line called '{near[0]}': rename it to start_number." if near else ""
    return f"{path} has no 'start_number' line, so the start number is 1.{hint}"


def get_digits(repo):
    """(base digits, variant digits) for this vault. Missing settings give the defaults, 5 and 3."""
    data = load(repo)
    result = []
    for key, default, (low, high) in (
            ("pn_base_digits", part_number.DEFAULT_BASE_DIGITS, part_number.BASE_DIGITS_RANGE),
            ("pn_variant_digits", part_number.DEFAULT_VARIANT_DIGITS, part_number.VARIANT_DIGITS_RANGE)):
        value = data.get(key)
        if value in (None, ""):
            value = default
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            raise ConfigError(f"{key} in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} must be a whole number from {low} to {high}, "
                              f"not {value!r}.")
        result.append(value)
    return tuple(result)


RELEASE_RULES = ("warn", "block", "off")


def get_release_rule(repo):
    """What a release does when the assembly uses parts that are out of date or not released:
    'warn' (the default: tell the user, who can go ahead), 'block' (refuse) or 'off' (say nothing)."""
    value = load(repo).get("release_rule")
    if value in (None, ""):
        return "warn"
    value = str(value).strip().lower()
    if value not in RELEASE_RULES:
        raise ConfigError(f"release_rule in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} must be one of "
                          f"{', '.join(RELEASE_RULES)}, not {value!r}.")
    return value


COMMIT_STYLES = ("per_part", "per_batch")


def get_commit_style(repo):
    """How Check In and Save Progress commit when several parts are done at once: 'per_part' (the default: one
    commit for each part) or 'per_batch' (one commit for all of them, which is faster)."""
    value = load(repo).get("commit_style")
    if value in (None, ""):
        return "per_part"
    value = str(value).strip().lower()
    if value not in COMMIT_STYLES:
        raise ConfigError(f"commit_style in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} must be one of "
                          f"{', '.join(COMMIT_STYLES)}, not {value!r}.")
    return value


def get_require_signatures(repo):
    """True if this vault refuses uploads of commits that aren't signed by a key on the team list."""
    value = load(repo).get("require_signatures", False)
    if not isinstance(value, bool):
        raise ConfigError(f"require_signatures in {layout.CONFIG_DIR}/{layout.CONFIG_FILE} must be true or false.")
    return value


def apply(repo):
    """Tell the rest of the program how this vault writes its part numbers. Returns (base, variant) digits."""
    compatibility.check_compatible(repo)
    digits = get_digits(repo)
    part_number.configure(*digits)
    return digits
