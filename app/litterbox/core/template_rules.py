"""
template_rules.py - the SolidWorks templates new files are made from, and which one a part uses.

The org has templates of its own, and each project may have more. Each is for one kind of file (a part, an assembly
or a drawing: core/file_types.TEMPLATES, by its extension). Among the org's templates of one kind exactly one is the
default, and the same among each project's. A part in a project gets its project's default of that kind if the
project has templates of that kind, else the org's default; every other template of the project and the org can be
chosen instead.

    choices(templates, file_types.DRAWING, "Rover")     # [Template]: Rover's (its default first), then the org's
    default_for(templates, file_types.DRAWING, "Rover")  # the one a Rover part gets, or None

The changes below return a new list and keep exactly one default in every group. Where the templates are kept is
vault/template_store.py.
"""

from dataclasses import dataclass, replace

from litterbox.core import file_types
from litterbox.errors import LitterboxError

ORG = ""                    # Template.project for the org's own templates
KINDS = (file_types.PART, file_types.ASSEMBLY, file_types.DRAWING)
LABELS = {file_types.PART: "Part", file_types.ASSEMBLY: "Assembly", file_types.DRAWING: "Drawing"}
NAME_MAX = 120


class TemplateError(LitterboxError):
    """A template change that can't be made (a name taken, a file that isn't a template)."""


@dataclass(frozen=True)
class Template:
    file: str                   # its file name in the vault's templates folder: "HCR drawing.drwdot"
    kind: str                   # file_types.PART, ASSEMBLY or DRAWING: what is made from it
    project: str = ORG          # the project it belongs to; ORG for the org's
    default: bool = False

    @property
    def name(self):
        """Its file name without the extension, as the window shows it."""
        return self.file.rsplit(".", 1)[0] if "." in self.file else self.file


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
        key = (template.kind, template.project.lower())
        if template.default and key not in keep:
            keep[key] = template.file.lower()
    for template in _sorted(templates):
        keep.setdefault((template.kind, template.project.lower()), template.file.lower())
    return [replace(t, default=keep[(t.kind, t.project.lower())] == t.file.lower()) for t in templates]


def find(templates, file):
    """The template with this file name (any capitals), or None."""
    return next((t for t in templates if _same(t.file, file)), None)


def check_file_name(file):
    """The name a new template is kept under: its own file name, which must be a template's. Raises TemplateError."""
    file = str(file or "").strip()
    if file_types.template_kind(file) is None:
        known = ", ".join(file_types.TEMPLATE_EXTENSIONS)
        raise TemplateError(f"{file or 'That'} isn't a template Litterbox knows. Templates end with {known}.")
    if len(file) > NAME_MAX or any(c in file for c in '\\/:*?"<>|') or file.startswith("."):
        raise TemplateError(f"{file} can't be used as a template's file name. Rename the file (shorter, without "
                            "\\ / : * ? \" < > |) and add it again.")
    return file


def added(templates, file, project=ORG):
    """The templates with a new one: `file` (its name) for the org (ORG) or a project. It is the default when it is
    the first of its kind there. Raises TemplateError if the vault has a template with that name already (names are
    shared by the org and every project, since all are in one folder)."""
    file = check_file_name(file)
    taken = find(templates, file)
    if taken is not None:
        whose = f"project {taken.project}" if taken.project else "the org"
        raise TemplateError(f"The vault already has a template called {taken.file} (for {whose}). Rename the file "
                            "and add it again.")
    kind = file_types.template_kind(file)
    new = Template(file, kind, project or ORG, default=not group(templates, kind, project))
    return normalized(list(templates) + [new])


def removed(templates, file):
    """The templates without `file`. If it was its group's default, the next one by name becomes the default."""
    if find(templates, file) is None:
        raise TemplateError(f"{file} isn't one of the vault's templates any more. Someone may have just removed it.")
    return normalized([t for t in templates if not _same(t.file, file)])


def made_default(templates, file):
    """The templates with `file` the default of its group."""
    chosen = find(templates, file)
    if chosen is None:
        raise TemplateError(f"{file} isn't one of the vault's templates any more. Someone may have just removed it.")
    return [replace(t, default=_same(t.file, file)) if t.kind == chosen.kind and _same(t.project, chosen.project)
            else t for t in templates]


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
