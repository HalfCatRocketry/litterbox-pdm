"""
projects.py - projects: a block of part numbers set aside for one project, chosen by the digits the part number
starts with.

With 6-digit part numbers, project Rover with prefix 12 owns 120000 to 129999 (every part number starting 12), and
New Part with Rover chosen asks only for the other 4 digits. Blocks never overlap, a prefix is always shorter than
the part number, and a part number outside every block belongs to no project. Parts with no project never get a
number inside a block.

The org's projects are kept in the vault's config (vault/config.py: get_projects) as
    projects:
    - name: Rover
      prefix: '12'
"""

from dataclasses import dataclass

from litterbox.core import part_number

NAME_MAX = 40                   # characters in a project's name


class ProjectError(part_number.PNError):
    """A project can't be used or added as given. The message is safe to show to a user."""


@dataclass(frozen=True)
class Project:
    name: str
    prefix: str                 # digits, kept as text so a leading 0 counts ('05')

    def block(self, digits=None):
        """(lowest, highest) part number in this project's block."""
        return block(self.prefix, digits)

    def contains(self, base, digits=None):
        low, high = self.block(digits)
        return low <= base <= high

    def remaining_digits(self, digits=None):
        """How many digits New Part asks for after the prefix."""
        return (digits or part_number.BASE_DIGITS) - len(self.prefix)

    def full_base(self, typed):
        """The part number made from the prefix and the digits typed after it: '12' + 34 -> 120034 (6 digits)."""
        return int(self.prefix) * 10 ** self.remaining_digits() + typed

    def describe(self, digits=None):
        """'Rover (120000 to 129999)'."""
        low, high = self.block(digits)
        return f"{self.name} ({part_number.format_base(low)} to {part_number.format_base(high)})"


def block(prefix, digits=None):
    """(lowest, highest) part number that starts with `prefix`. Zero is never a part number, so a block of 0s starts
    at 1."""
    digits = digits or part_number.BASE_DIGITS
    rest = digits - len(prefix)
    low = int(prefix) * 10 ** rest
    return max(low, part_number.MIN_BASE), low + 10 ** rest - 1


def project_of(base, projects):
    """The project whose block holds this part number, or None."""
    return next((project for project in projects if project.contains(base)), None)


def find(name, projects):
    """The project with this name (capitals don't matter). Raises ProjectError if there is none."""
    wanted = str(name or "").strip().lower()
    for project in projects:
        if project.name.lower() == wanted:
            return project
    raise ProjectError(f"There is no project called {name!r}.")


def outside_blocks(projects):
    """A test for New Part with no project: True for a part number that is in no project's block."""
    blocks = [project.block() for project in projects]
    return lambda base: not any(low <= base <= high for low, high in blocks)


def check_name(text):
    """A project's name, tidied to one line. Raises ProjectError if it can't be used."""
    name = " ".join(str(text or "").split())
    if not name:
        raise ProjectError("A project needs a name.")
    if len(name) > NAME_MAX:
        raise ProjectError(f"A project's name can be at most {NAME_MAX} characters.")
    if name.lower() == "none":
        raise ProjectError("'None' means no project, so a project can't be called that.")
    return name


def check_prefix(text, digits=None):
    """The digits a project's part numbers start with. Raises ProjectError if they can't be used."""
    digits = digits or part_number.BASE_DIGITS
    prefix = str(text or "").strip()
    if not prefix:
        raise ProjectError("Enter the digits the project's part numbers start with (for example 12).")
    if not (prefix.isascii() and prefix.isdigit()):
        raise ProjectError("The project's starting digits must be digits only (for example 12).")
    if len(prefix) >= digits:
        raise ProjectError(f"Part numbers have {digits} digits, so a project can start with at most {digits - 1} of "
                           "them (the rest are typed for each part).")
    return prefix


def new_project(name, prefix, projects, digits=None):
    """A project that can be added to `projects`. Raises ProjectError if the name is taken or the block overlaps
    another project's."""
    name, prefix = check_name(name), check_prefix(prefix, digits)
    for other in projects:
        if other.name.lower() == name.lower():
            raise ProjectError(f"There is already a project called {other.name}.")
        if other.prefix.startswith(prefix) or prefix.startswith(other.prefix):
            raise ProjectError(f"Part numbers starting {prefix} would overlap project {other.describe(digits)}.")
    return Project(name, prefix)


def from_data(data, digits=None):
    """The projects from the vault's config (a list of {name, prefix}). Raises ProjectError if the list is broken,
    so a hand edit can never make two projects share numbers."""
    if data in (None, ""):
        return []
    if not isinstance(data, list):
        raise ProjectError("projects must be a list of projects, each with a name and a prefix.")
    projects = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ProjectError("Each project must have a name and a prefix.")
        projects.append(new_project(entry.get("name"), entry.get("prefix"), projects, digits))
    return projects


def to_data(projects):
    return [{"name": project.name, "prefix": project.prefix} for project in projects]
