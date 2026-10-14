"""
config.py - the vault's shared settings.

They live INSIDE the vault, in .litterbox/config.yaml, so the whole team uses the
same ones:

    org: HCR              the org code that starts every part number
    start_number: 10001   the first part number to hand out (optional, default 1). Numbers count up from here to
                          the highest the digits allow, then start again at 1 and stop just below it
    pn_base_digits: 5     digits in the part number (HCR-10001-001), default 5
    pn_variant_digits: 3  digits in the variant number (HCR-10001-001), default 3
    format_version: 1     the layout of the vault's files (see version.py), default 1
    min_litterbox_version: 0.1.0   the oldest Litterbox allowed in this vault, default none

Choose the digit counts when the vault is set up. Changing them once part
numbers exist would leave the old records and files with the wrong format, so
save() refuses to.

If the file doesn't exist yet, the org code is worked out from the part numbers
already in the vault (as long as they all use the same one). A vault with no part
numbers and no config file needs the file created by hand:

    hcr-litterbox\\.litterbox\\config.yaml

(init_vault.py will create it for new vaults.)

This is different from settings.py, which holds YOUR personal settings and lives
outside the vault.
"""

from pathlib import Path

import yaml

from litterbox.core import pn as pn_module
from litterbox.records import registry
from litterbox import version
from litterbox.core.pn import PNError, check_org

CONFIG_DIR = ".litterbox"
CONFIG_FILE = "config.yaml"


class ConfigError(Exception):
    """Something is wrong with the vault's settings. The message is safe to show to a user."""


class NoOrgError(ConfigError):
    """The vault has no org code yet (no config file and no part numbers to infer it from)."""


def config_path(repo):
    return Path(repo) / CONFIG_DIR / CONFIG_FILE


def load(repo):
    """The vault's settings as a dict. A missing file is fine and gives {}."""
    path = config_path(repo)
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"Could not read {CONFIG_DIR}/{CONFIG_FILE}: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_DIR}/{CONFIG_FILE} should contain settings like 'org: HCR'.")
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
            raise ConfigError(f"The org code in {CONFIG_DIR}/{CONFIG_FILE} is not valid. {e}")

    orgs = sorted({pn.org for pn in registry.list_pns(repo)})
    if len(orgs) == 1:
        return orgs[0]
    if not orgs:
        raise NoOrgError(
            "This vault doesn't have an org code yet. Create the file "
            f"{CONFIG_DIR}/{CONFIG_FILE} in the vault, containing a line like:\n  org: HCR")
    raise ConfigError(
        f"This vault has part numbers from several orgs ({', '.join(orgs)}), so Litterbox can't "
        f"tell which to use. Set one in {CONFIG_DIR}/{CONFIG_FILE}, for example:\n  org: {orgs[0]}")


def get_start_number(repo):
    """The first part number to hand out (default 1). Numbers count up from it, then round again from 1 (see pn.next_base)."""
    value = load(repo).get("start_number")
    if value in (None, ""):
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"start_number in {CONFIG_DIR}/{CONFIG_FILE} must be a whole number, 1 or higher "
                          f"(for example 10001), not {value!r}.")
    return value


def explain_start_number(repo):
    """One sentence saying where the start number came from (or why it is the default 1). For the Import window."""
    path = config_path(repo)
    try:
        if not path.is_file():
            text = f"There is no settings file at {path}, so the start number is 1."
            others = [p for p in (Path(repo) / CONFIG_DIR / "config.yml", Path(repo) / "config.yaml",
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
            ("pn_base_digits", pn_module.DEFAULT_BASE_DIGITS, pn_module.BASE_DIGITS_RANGE),
            ("pn_variant_digits", pn_module.DEFAULT_VARIANT_DIGITS, pn_module.VARIANT_DIGITS_RANGE)):
        value = data.get(key)
        if value in (None, ""):
            value = default
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            raise ConfigError(f"{key} in {CONFIG_DIR}/{CONFIG_FILE} must be a whole number from {low} to {high}, "
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
        raise ConfigError(f"release_rule in {CONFIG_DIR}/{CONFIG_FILE} must be one of "
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
        raise ConfigError(f"commit_style in {CONFIG_DIR}/{CONFIG_FILE} must be one of "
                          f"{', '.join(COMMIT_STYLES)}, not {value!r}.")
    return value


def set_values(repo, **values):
    """Change vault settings that anyone may be allowed to edit (see vault_settings.py). Only the values given are
    changed. Raises ConfigError for an unknown setting or a bad value."""
    data = load(repo)
    original = dict(data)
    for key, value in values.items():
        if key == "commit_style":
            if value not in COMMIT_STYLES:
                raise ConfigError(f"commit_style must be one of {', '.join(COMMIT_STYLES)}.")
            if value == "per_part":
                data.pop(key, None)                  # the default needs no line
            else:
                data[key] = value
        elif key == "release_rule":
            if value not in RELEASE_RULES:
                raise ConfigError(f"release_rule must be one of {', '.join(RELEASE_RULES)}.")
            if value == "warn":
                data.pop(key, None)
            else:
                data[key] = value
        elif key == "require_signatures":
            if not isinstance(value, bool):
                raise ConfigError("require_signatures must be true or false.")
            if value:
                data[key] = True
            else:
                data.pop(key, None)
        else:
            raise ConfigError(f"'{key}' is not a setting that can be changed here.")
    path = config_path(repo)
    if data == original:
        return data                                  # nothing to change: leave the file (and its comments) alone
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp-config.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    tmp.replace(path)
    return data


def get_require_signatures(repo):
    """True if this vault refuses uploads of commits that aren't signed by a key on the team list."""
    value = load(repo).get("require_signatures", False)
    if not isinstance(value, bool):
        raise ConfigError(f"require_signatures in {CONFIG_DIR}/{CONFIG_FILE} must be true or false.")
    return value


def check_compatible(repo):
    """Raise ConfigError if this vault needs a newer Litterbox than this one (see version.py)."""
    data = load(repo)
    layout = data.get("format_version", 1)
    if isinstance(layout, bool) or not isinstance(layout, int) or layout < 1:
        raise ConfigError(f"format_version in {CONFIG_DIR}/{CONFIG_FILE} must be a whole number, 1 or higher.")
    if layout > version.VAULT_FORMAT:
        raise ConfigError(
            f"This vault was set up by a newer Litterbox (vault format {layout}; this copy only understands "
            f"up to {version.VAULT_FORMAT}). Update Litterbox to open it. You have {version.VERSION}.")
    wanted = data.get("min_litterbox_version")
    if wanted not in (None, ""):
        try:
            too_old = version.parse(wanted) > version.parse(version.VERSION)
        except ValueError:
            raise ConfigError(f"min_litterbox_version in {CONFIG_DIR}/{CONFIG_FILE} should look like 0.1.0.")
        if too_old:
            raise ConfigError(f"This vault needs Litterbox {wanted} or newer. You have {version.VERSION}. "
                              "Update Litterbox to continue.")


def stamp(repo, min_version=None):
    """Record this program's vault format in the vault's config, and optionally the oldest Litterbox allowed.

    Raising min_version makes everyone update before they can work in the vault. It never lowers an
    existing minimum."""
    data = load(repo)
    data["format_version"] = max(version.VAULT_FORMAT, data.get("format_version", 1)
                                 if isinstance(data.get("format_version"), int) else 1)
    if min_version is not None:
        version.parse(min_version)
        current = data.get("min_litterbox_version")
        if current in (None, "") or version.parse(min_version) > version.parse(current):
            data["min_litterbox_version"] = str(min_version).lstrip("vV")
    path = config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def apply(repo):
    """Tell the rest of the program how this vault writes its part numbers. Returns (base, variant) digits."""
    check_compatible(repo)
    digits = get_digits(repo)
    pn_module.configure(*digits)
    return digits


def save(repo, org=None, start_number=None, base_digits=None, variant_digits=None):
    """Create or update the vault's config file. Only the values given are changed.

    The digit counts can't be changed once the vault has part numbers in it.
    """
    data = load(repo)
    if org is not None:
        data["org"] = check_org(org)
    if start_number is not None:
        if isinstance(start_number, bool) or not isinstance(start_number, int) or start_number < 1:
            raise ConfigError("The starting part number must be a whole number, 1 or higher.")
        data["start_number"] = start_number
    current = dict(zip(("pn_base_digits", "pn_variant_digits"), get_digits(repo)))
    for key, value, (low, high) in (
            ("pn_base_digits", base_digits, pn_module.BASE_DIGITS_RANGE),
            ("pn_variant_digits", variant_digits, pn_module.VARIANT_DIGITS_RANGE)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            raise ConfigError(f"{key} must be a whole number from {low} to {high}.")
        if value != current[key] and _has_records(repo):
            raise ConfigError(
                "This vault already has part numbers, so the number of digits can't be changed. "
                "The existing records and files would no longer match.")
        data[key] = value
    path = config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp-config.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    tmp.replace(path)
    return data


def _has_records(repo):
    folder = registry.log_dir(repo)
    return folder.is_dir() and any(folder.glob("*.yaml"))
