"""
template_rules.py - the SolidWorks templates new files are made from, and which one a part uses.

The org has templates of its own, and each project may have more. Each is for one kind of file (a part, an assembly
or a drawing: core/file_types.TEMPLATES, by its extension). Among the org's templates of one kind exactly one is the
default, and the same among each project's. A part in a project gets its project's default of that kind if the
project has templates of that kind, else the org's default; every other template of the project and the org can be
chosen instead.

    choices(templates, file_types.DRAWING, "Rover")     # [Template]: Rover's (its default first), then the org's
    default_for(templates, file_types.DRAWING, "Rover")  # the one a Rover part gets, or None

The org's templates sit at the top of the vault's templates folder, and each project's in a folder of its own, named
after the project (folder_name). A template is known by its `key`, its path inside that folder: "HCR A.drwdot" for
the org's, "Rover/Rover A3.drwdot" for a project's. So the org and each project may each have a template of the same
file name. The changes below return a new list and keep exactly one default in every group. Where the templates are
kept is vault/template_store.py.
"""

from dataclasses import dataclass, replace

from litterbox.core import file_types
from litterbox.errors import LitterboxError

ORG = ""                    # Template.project for the org's own templates
KINDS = (file_types.PART, file_types.ASSEMBLY, file_types.DRAWING)
LABELS = {file_types.PART: "Part", file_types.ASSEMBLY: "Assembly", file_types.DRAWING: "Drawing"}
NAME_MAX = 120
BAD_CHARACTERS = '\\/:*?"<>|'
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


class TemplateError(LitterboxError):
    """A template change that can't be made (a name taken, a file that isn't a template)."""


def folder_name(project):
    """The folder a project's templates are kept in, inside the templates folder: its name, with the characters
    Windows doesn't allow in a folder's name made "-" ("Rover/Mars" -> "Rover-Mars"). "" for the org's."""
    if not project:
        return ""
    name = "".join("-" if c in BAD_CHARACTERS or ord(c) < 32 else c for c in str(project)).strip().rstrip(".")
    if not name or name.lower() in WINDOWS_RESERVED:
        name = f"{name}_"
    return name


@dataclass(frozen=True)
class Template:
    file: str                   # its file name: "HCR drawing.drwdot"
    kind: str                   # file_types.PART, ASSEMBLY or DRAWING: what is made from it
    project: str = ORG          # the project it belongs to; ORG for the org's
    default: bool = False

    @property
    def name(self):
        """Its file name without the extension, as the window shows it."""
        return self.file.rsplit(".", 1)[0] if "." in self.file else self.file

    @property
    def key(self):
        """Its path inside the templates folder, which says which template it is: "Rover/Rover A3.drwdot"."""
        folder = folder_name(self.project)
        return f"{folder}/{self.file}" if folder else self.file


def _same(a, b):
    return str(a or "").lower() == str(b or "").lower()


def _sorted(templates):
    return sorted(templates, key=lambda t: (t.name.lower(), t.file.lower()))


def group(templates, kind, project=ORG):
    """The templates of one kind that belong to the org (ORG) or one project, by name."""
    return _sorted(t for t in templates if t.kind == kind and _same(t.project, project))


def normalized(templates):
    """The same templates with exactly one default in every group (the first marked one, by name, else the first)."""
    keep = {}
    for template in _sorted(templates):
        group_key = (template.kind, template.project.lower())
        if template.default and group_key not in keep:
            keep[group_key] = template.key.lower()
    for template in _sorted(templates):
        keep.setdefault((template.kind, template.project.lower()), template.key.lower())
    return [replace(t, default=keep[(t.kind, t.project.lower())] == t.key.lower()) for t in templates]


def find(templates, key):
    """The template with this key (any capitals), or None."""
    return next((t for t in templates if _same(t.key, key)), None)


def check_file_name(file):
    """The name a new template is kept under: its own file name, which must be a template's. Raises TemplateError."""
    file = str(file or "").strip()
    if file_types.template_kind(file) is None:
        known = ", ".join(file_types.TEMPLATE_EXTENSIONS)
        raise TemplateError(f"{file or 'That'} isn't a template Litterbox knows. Templates end with {known}.")
    if len(file) > NAME_MAX or any(c in file for c in BAD_CHARACTERS) or file.startswith("."):
        raise TemplateError(f"{file} can't be used as a template's file name. Rename the file (shorter, without "
                            "\\ / : * ? \" < > |) and add it again.")
    return file


def owner_text(project):
    return f"project {project}" if project else "the org"


def added(templates, file, project=ORG):
    """The templates with a new one: `file` (its name) for the org (ORG) or a project. It is the default when it is
    the first of its kind there. Raises TemplateError if that owner has a template of that name already."""
    file = check_file_name(file)
    new = Template(file, file_types.template_kind(file), project or ORG)
    if find(templates, new.key) is not None:
        raise TemplateError(f"{owner_text(project).capitalize()} already has a template called {file}. Rename the "
                            "file and add it again, or remove the old one first.")
    new = replace(new, default=not group(templates, new.kind, project))
    return normalized(list(templates) + [new])


def _existing(templates, key):
    found = find(templates, key)
    if found is None:
        raise TemplateError(f"{key} isn't one of the vault's templates any more. Someone may have just removed it.")
    return found


def removed(templates, key):
    """The templates without this one. If it was its group's default, the next one by name becomes the default."""
    gone = _existing(templates, key)
    return normalized([t for t in templates if t is not gone])


def made_default(templates, key):
    """The templates with this one the default of its group."""
    chosen = _existing(templates, key)
    return [replace(t, default=t is chosen) if t.kind == chosen.kind and _same(t.project, chosen.project) else t
            for t in templates]


def renamed_project(templates, old, new):
    """The templates with project `old`'s now `new`'s."""
    return [replace(t, project=new) if t.project and _same(t.project, old) else t for t in templates]


def choices(templates, kind, project=ORG):
    """The templates a part of `project` (ORG for none) may use for a file of this kind: the project's, its default
    first, then the org's, its default first."""
    found = []
    for owner in ([project] if project else []) + [ORG]:
        mine = group(templates, kind, owner)
        found += [t for t in mine if t.default] + [t for t in mine if not t.default]
    return found


def default_for(templates, kind, project=ORG):
    """The template a part of `project` gets for a file of this kind: its project's default if the project has
    templates of that kind, else the org's default; None if there is neither."""
    found = choices(templates, kind, project)
    return found[0] if found else None
