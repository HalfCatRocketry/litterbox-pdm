"""
config_write.py - changing the vault's shared settings (.litterbox/config.yaml).

A setting at its default has its line removed. The digit counts can't change once part numbers exist: old records
and files would be left with the wrong format, so save() refuses.
"""

import yaml

from litterbox import version
from litterbox.core import part_number
from litterbox.core import projects as project_rules
from litterbox.core.part_number import check_org
from litterbox.records import record_store
from litterbox.vault import config


def set_values(repo, **values):
    """Change vault settings that anyone may be allowed to edit (see vault_settings.py). Only the values given are
    changed. Raises ConfigError for an unknown setting or a bad value."""
    data = config.load(repo)
    original = dict(data)
    for key, value in values.items():
        if key == "commit_style":
            if value not in config.COMMIT_STYLES:
                raise config.ConfigError(f"commit_style must be one of {', '.join(config.COMMIT_STYLES)}.")
            if value == "per_part":
                data.pop(key, None)                  # the default needs no line
            else:
                data[key] = value
        elif key == "release_rule":
            if value not in config.RELEASE_RULES:
                raise config.ConfigError(f"release_rule must be one of {', '.join(config.RELEASE_RULES)}.")
            if value == "warn":
                data.pop(key, None)
            else:
                data[key] = value
        elif key == "require_signatures":
            if not isinstance(value, bool):
                raise config.ConfigError("require_signatures must be true or false.")
            if value:
                data[key] = True
            else:
                data.pop(key, None)
        elif key == "assembly_variant_start":
            data[key] = config.check_assembly_variant(value, config.get_digits(repo)[1])
        elif key == "projects":
            try:
                project_rules.from_data(project_rules.to_data(value), config.get_digits(repo)[0])   # never overlapping
            except project_rules.ProjectError as e:
                raise config.ConfigError(str(e)) from None
            if value:
                data[key] = project_rules.to_data(value)
                _require_at_least(data, version.VERSION)     # older Litterbox would hand out numbers in the blocks
            else:
                data.pop(key, None)
        else:
            raise config.ConfigError(f"'{key}' is not a setting that can be changed here.")
    path = config.config_path(repo)
    if data == original:
        return data                                  # nothing to change: leave the file (and its comments) alone
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp-config.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)
    return data


def _require_at_least(data, min_version):
    current = data.get("min_litterbox_version")
    if current in (None, "") or version.parse(min_version) > version.parse(current):
        data["min_litterbox_version"] = str(min_version).lstrip("vV")


def stamp(repo, min_version=None):
    """Record this program's vault format in the vault's config, and optionally the oldest Litterbox allowed.

    Raising min_version makes everyone update before they can work in the vault. It never lowers an
    existing minimum."""
    data = config.load(repo)
    data["format_version"] = max(version.VAULT_FORMAT, data.get("format_version", 1)
                                 if isinstance(data.get("format_version"), int) else 1)
    if min_version is not None:
        version.parse(min_version)
        current = data.get("min_litterbox_version")
        if current in (None, "") or version.parse(min_version) > version.parse(current):
            data["min_litterbox_version"] = str(min_version).lstrip("vV")
    path = config.config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def save(repo, org=None, start_number=None, base_digits=None, variant_digits=None, org_name=None):
    """Create or update the vault's config file. Only the values given are changed (org_name="" removes the name).

    The digit counts can't be changed once the vault has part numbers in it.
    """
    data = config.load(repo)
    if org is not None:
        data["org"] = check_org(org)
    if org_name is not None:
        name = config.check_org_name(org_name)
        if name:
            data["org_name"] = name
        else:
            data.pop("org_name", None)
    if start_number is not None:
        if isinstance(start_number, bool) or not isinstance(start_number, int) or start_number < 1:
            raise config.ConfigError("The starting part number must be a whole number, 1 or higher.")
        data["start_number"] = start_number
    current = dict(zip(("pn_base_digits", "pn_variant_digits"), config.get_digits(repo)))
    for key, value, (low, high) in (
            ("pn_base_digits", base_digits, part_number.BASE_DIGITS_RANGE),
            ("pn_variant_digits", variant_digits, part_number.VARIANT_DIGITS_RANGE)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
            raise config.ConfigError(f"{key} must be a whole number from {low} to {high}.")
        if value != current[key] and _has_records(repo):
            raise config.ConfigError(
                "This vault already has part numbers, so the number of digits can't be changed. "
                "The existing records and files would no longer match.")
        data[key] = value
    path = config.config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".tmp-config.yaml")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    tmp.replace(path)
    return data


def _has_records(repo):
    folder = record_store.log_dir(repo)
    return folder.is_dir() and any(folder.glob("*.yaml"))
