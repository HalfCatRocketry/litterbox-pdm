"""
eco_store.py - reading and writing ECO files (ECO/ECO-0001.yaml), and which number comes next.

ECO files are read-only on disk, like a released part's files: save() opens one up only for the moment it writes,
and only Litterbox writes them (under the locks of the ECO's parts, see eco_lifecycle.py). Never runs git.
"""

import os
import stat
import tempfile
from pathlib import Path

import yaml

from litterbox import layout
from litterbox.change_orders import eco_model
from litterbox.util import fast_yaml


def eco_dir(repo):
    return Path(repo) / layout.ECO_DIR_NAME


def relpath(number):
    """'ECO-0003' -> 'ECO/ECO-0003.yaml' (relative to the vault, as git wants it)."""
    return f"{layout.ECO_DIR_NAME}/{number}.yaml"


def path(repo, number):
    return Path(repo) / relpath(number)


def exists(repo, number):
    return path(repo, number).is_file()


def numbers(repo):
    """Every ECO number in the folder, in order."""
    folder = eco_dir(repo)
    if not folder.is_dir():
        return []
    found = [p.stem for p in folder.glob("*.yaml") if eco_model.number_value(p.stem) is not None]
    return sorted(found, key=eco_model.number_value)


def next_number(repo):
    """The number after the highest one used (numbers are never reused)."""
    used = [eco_model.number_value(n) for n in numbers(repo)]
    return eco_model.number_text(max(used, default=0) + 1)


def load(repo, number):
    file = path(repo, number)
    try:
        data = fast_yaml.safe_load(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise eco_model.EcoError(f"There is no {number} in your copy of the vault. Try Get Latest.") from None
    except (OSError, yaml.YAMLError) as e:
        raise eco_model.EcoError(f"{number} can't be read: {e}") from None
    eco = eco_model.Eco.from_dict(data)
    if eco.number != number:
        raise eco_model.EcoError(f"{relpath(number)} says it is {eco.number}.")
    return eco


def save(repo, eco):
    """Write the ECO's file (all at once), and leave it read-only."""
    file = path(repo, eco.number)
    file.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(eco.to_dict(), sort_keys=False, allow_unicode=True, width=100)
    if file.exists():
        os.chmod(file, file.stat().st_mode | stat.S_IWUSR)
    with tempfile.NamedTemporaryFile("w", dir=file.parent, suffix=".tmp", delete=False, encoding="utf-8",
                                     newline="\n") as handle:
        try:
            handle.write(text)
        except BaseException:
            handle.close()
            os.unlink(handle.name)                  # never leave a half-written file in the ECO folder
            raise
    os.replace(handle.name, file)
    os.chmod(file, stat.S_IREAD)
    return relpath(eco.number)


def load_all(repo):
    """(every ECO that can be read, newest first; {number: why} for any that can't)."""
    ecos, problems = [], {}
    for number in reversed(numbers(repo)):
        try:
            ecos.append(load(repo, number))
        except eco_model.EcoError as e:
            problems[number] = str(e)
    return ecos, problems
