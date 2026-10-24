"""
template_text.py - the vault's SolidWorks templates in words (core/template_rules.py): a template as a choice in a
list, the rows of Team > Templates..., and what the window says after a change.
"""

from litterbox.core import template_rules

NONE = "None: I'll save the file myself"
ORG_TITLE = "The org"


def owner_name(project):
    return project or "org"


def choice_label(template):
    """A template as a list shows it: "HCR A size (org default)", "Rover A3 (Rover)"."""
    owner = owner_name(template.project)
    kind = template_rules.LABELS[template.kind].lower()
    return f"{template.name}  ({owner} {kind} default)" if template.default else f"{template.name}  ({owner} {kind})"


def choice_map(templates, none=True):
    """{label: template key} in list order, for an option menu; NONE (None) last when `none`."""
    found = {choice_label(t): t.key for t in templates}
    if none:
        found[NONE] = None
    return found


def rows(templates, project):
    """[(key, name, kind, "Default" or "")] for one owner's templates (the org's: template_rules.ORG), by kind
    then name."""
    found = []
    for kind in template_rules.KINDS:
        for t in template_rules.group(templates, kind, project):
            found.append((t.key, t.name, template_rules.LABELS[kind], "Default" if t.default else ""))
    return found


def owner_title(project):
    return f"Project {project}" if project else ORG_TITLE


def none_yet(kind_label, project=""):
    """What a list of templates says when there are none of a kind."""
    where = f"project {project} or the org" if project else "the org"
    return f"No {kind_label.lower()} templates for {where} yet (Team > Templates...)."


def done_text(action, key):
    name = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"add": f"Template {name} added", "remove": f"Template {name} removed",
            "default": f"Template {name} is now the default"}[action]


JOB_LABELS = {"add": "Adding a template", "remove": "Removing a template", "default": "Changing the default template"}

HOW_IT_WORKS = ("New Part, New Assembly, New Model... and New Drawing... make the file from a template. A part in a "
                "project gets its project's default of that kind, if the project has any templates of that kind, "
                "otherwise the org's default; the others can be chosen instead. Admins and the Owner change the "
                "org's templates; a project's Lead changes its own.")
