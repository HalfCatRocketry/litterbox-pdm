"""
config.py - the vault's shared settings, read from .litterbox/config.yaml (inside the vault, so the whole
team uses the same ones):

    org: HCR              the org code that starts every part number
    org_name: Hidden Creek Robotics   the org's full name, for people to read (optional, default the code)
    start_number: 10001   the first part number to hand out (optional, default 1). Numbers count up from here to
                          the highest the digits allow, then start again at 1 and stop just below it
    pn_base_digits: 5     digits in the part number (HCR-10001-001), default 5
    pn_variant_digits: 3  digits in the variant number (HCR-10001-001), default 3
    format_version: 1     the layout of the vault's files (see version.py), default 1
    min_litterbox_version: 0.1.0   the oldest Litterbox allowed in this vault, default none
    commit_style, release_rule, require_signatures   see their get_ functions below
    solidworks_version: 2024   the SolidWorks everyone works in (cad/solidworks_versions.py), default none (no check)
    currency: USD         the team's currency (core/currency.py): costs are shown with its symbol, default none
    assembly_variant_start: 500   New Assembly's variants start here, New Part's stay below it (default 5 followed
                          by zeros: 500 with 3-digit variants). An Admin can change it at any time
    projects:             blocks of part numbers set aside for projects (core/projects.py), each a name and the
    - name: Rover         digits its part numbers start with. Only added to, never changed (settings_admin.py)
      prefix: '12'

If the file doesn't exist yet, the org code is worked out from the part numbers already in the vault (as long as
they all use the same one). vault/create_vault.py writes the file for new vaults.

Writing the settings is in config_write.py; checking that this Litterbox may open the vault is in
compatibility.py. This is different from user/settings.py, which holds YOUR personal settings and lives outside
the vault.
"""

from pathlib import Path

import yaml

from litterbox import layout
from litterbox.cad import solidworks_versions
from litterbox.core import currency as currencies
from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.core.part_number import PNError, check_org
from litterbox.records import record_store
from litterbox.util import fast_yaml
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
            data = fast_yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"Could not read {layout.CONFIG_PATH}: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{layout.CONFIG_PATH} should contain settings like 'org: HCR'.")
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
            raise ConfigError(f"The org code in {layout.CONFIG_PATH} is not valid. {e}")

    orgs = sorted({pn.org for pn in record_store.list_pns(repo)})
    if len(orgs) == 1:
        return orgs[0]
    if not orgs:
        raise NoOrgError(
            "This vault doesn't have an org code yet. Create the file "
            f"{layout.CONFIG_PATH} in the vault, containing a line like:\n  org: HCR")
    raise ConfigError(
        f"This vault has part numbers from several orgs ({', '.join(orgs)}), so Litterbox can't "
        f"tell which to use. Set one in {layout.CONFIG_PATH}, for example:\n  org: {orgs[0]}")


ORG_NAME_MAX = 80               # characters in an org's full name


def check_org_name(text):
    """An org's full name, tidied: one line, spaces trimmed, at most ORG_NAME_MAX characters. "" means none.
    Raises ConfigError if it can't be used."""
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ConfigError("The org name must be text.")
    name = " ".join(text.split())
    if len(name) > ORG_NAME_MAX:
        raise ConfigError(f"The org name can be at most {ORG_NAME_MAX} characters.")
    return name


def get_org_name(repo):
    """The org's full name ('Hidden Creek Robotics'), or the org code when the vault has no name set."""
    try:
        name = check_org_name(load(repo).get("org_name"))
    except ConfigError:
        name = ""
    return name or get_org(repo)


def get_start_number(repo):
    """The first part number to hand out (default 1). Numbers count up from it, then round again from 1 (see pn.next_base)."""
    value = load(repo).get("start_number")
    if value in (None, ""):
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"start_number in {layout.CONFIG_PATH} must be a whole number, 1 or higher "
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
            raise ConfigError(f"{key} in {layout.CONFIG_PATH} must be a whole number from {low} to {high}, "
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
        raise ConfigError(f"release_rule in {layout.CONFIG_PATH} must be one of "
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
        raise ConfigError(f"commit_style in {layout.CONFIG_PATH} must be one of "
                          f"{', '.join(COMMIT_STYLES)}, not {value!r}.")
    return value


def get_projects(repo):
    """The org's projects (core/projects.py Project), in the order they were added. [] if there are none."""
    base_digits, _variant_digits = get_digits(repo)
    try:
        return project_rules.from_data(load(repo).get("projects"), base_digits)
    except project_rules.ProjectError as e:
        raise ConfigError(f"projects in {layout.CONFIG_PATH}: {e}") from None


def default_assembly_variant(variant_digits=None):
    """The variant assemblies start at unless the org chose another: 500 with 3-digit variants, 50 with 2."""
    return 5 * 10 ** ((variant_digits or part_number.VARIANT_DIGITS) - 1)


def check_assembly_variant(value, variant_digits=None):
    """The variant assemblies start at, checked: there must be room for part variants below it (from 1) and for
    assembly variants from it. Raises ConfigError."""
    highest = 10 ** (variant_digits or part_number.VARIANT_DIGITS) - 1
    if isinstance(value, bool) or not isinstance(value, int) or not (2 <= value <= highest):
        raise ConfigError(f"The variant assemblies start at must be a whole number from 2 to {highest} (parts use "
                          "the variants below it).")
    return value


def get_assembly_variant_start(repo):
    """The first variant New Assembly uses (New Part uses the ones below it)."""
    _base_digits, variant_digits = get_digits(repo)
    value = load(repo).get("assembly_variant_start")
    if value in (None, ""):
        return default_assembly_variant(variant_digits)
    try:
        return check_assembly_variant(value, variant_digits)
    except ConfigError as e:
        raise ConfigError(f"assembly_variant_start in {layout.CONFIG_PATH}: {e}") from None


def get_require_signatures(repo):
    """True if this vault refuses uploads of commits that aren't signed by a key on the team list."""
    value = load(repo).get("require_signatures", False)
    if not isinstance(value, bool):
        raise ConfigError(f"require_signatures in {layout.CONFIG_PATH} must be true or false.")
    return value


def check_solidworks_version(value):
    """A SolidWorks version for the vault, as a year (2024), or None for none. Raises ConfigError."""
    if value in (None, ""):
        return None
    low, high = solidworks_versions.FIRST_YEAR, solidworks_versions.LAST_YEAR
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise ConfigError(f"The SolidWorks version must be a year from {low} to {high}, like 2024.")
    return value


def get_solidworks_version(repo):
    """The SolidWorks everyone in this vault works in, as a year (2024), or None if the org hasn't chosen one."""
    try:
        return check_solidworks_version(load(repo).get("solidworks_version"))
    except ConfigError as e:
        raise ConfigError(f"solidworks_version in {layout.CONFIG_PATH}: {e}") from None


def check_currency(value):
    """A currency code for the vault ('USD'), or None for none. Raises ConfigError."""
    try:
        return currencies.check(value)
    except currencies.CurrencyError as e:
        raise ConfigError(str(e)) from None


def get_currency(repo):
    """The team's currency code ('USD'), or None if the org hasn't chosen one."""
    try:
        return check_currency(load(repo).get("currency"))
    except ConfigError as e:
        raise ConfigError(f"currency in {layout.CONFIG_PATH}: {e}") from None


def currency_or_none(repo):
    """get_currency, but None when the settings can't be read: for showing costs, which must never fail."""
    try:
        return get_currency(repo)
    except (ConfigError, OSError):
        return None


def apply(repo):
    """Tell the rest of the program how this vault writes its part numbers. Returns (base, variant) digits."""
    compatibility.check_compatible(repo)
    digits = get_digits(repo)
    part_number.configure(*digits)
    return digits
