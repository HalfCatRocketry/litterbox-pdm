"""
project_text.py - the Projects window's words: the list of projects, what a project's starting digits would give
it (checked as you type), and the questions before a project is added, changed or deleted.
"""

from litterbox.core import part_number
from litterbox.core import projects as project_rules

SHORT_NOTE = ("As an Admin you may go ahead anyway. Anyone else is refused digits this few (Team > Vault Settings... "
              "sets the minimum).")


def project_lines(projects):
    """One line per project for the window's list."""
    if not projects:
        return ["No projects yet."]
    return [f"{project.name}    starts {project.prefix}    "
            f"{part_number.format_base(project.block()[0])} to {part_number.format_base(project.block()[1])}"
            for project in projects]


def preview(name, prefix, projects, used_in_block=()):
    """(text, kind) shown under the boxes: kind is "" (nothing typed), "ok", "warn" or "error". `used_in_block` is
    the part numbers already in the block (they keep no project)."""
    if not str(prefix or "").strip():
        return "", ""
    try:
        prefix = project_rules.check_prefix(prefix)
        project_rules.new_project(name if str(name or "").strip() else "(unnamed)", prefix, projects)
    except project_rules.ProjectError as e:
        return str(e), "error"
    low, high = project_rules.block(prefix)
    digits = part_number.BASE_DIGITS - len(prefix)
    text = (f"Part numbers {part_number.format_base(low)} to {part_number.format_base(high)}. New Part asks for the "
            f"other {digits} digit{'s' if digits != 1 else ''}.")
    if used_in_block:
        count = len(used_in_block)
        shown = ", ".join(str(pn) for pn in sorted(used_in_block)[:3]) + (", ..." if count > 3 else "")
        return (f"{text}\n{count} part{'s are' if count != 1 else ' is'} already in this block ({shown}). "
                f"{'They keep' if count != 1 else 'It keeps'} no project."), "warn"
    return text, "ok"


def confirm_text(name, prefix, used_in_block=()):
    """The question before a project is added."""
    low, high = project_rules.block(prefix)
    lines = [f"Add project {name}, with part numbers {part_number.format_base(low)} to "
             f"{part_number.format_base(high)}?"]
    if used_in_block:
        lines += ["", f"{len(used_in_block)} part number(s) already in this block keep no project."]
    return "\n".join(lines)


def _some(pns, limit=5):
    shown = ", ".join(str(pn) for pn in sorted(pns)[:limit])
    return shown + (f" and {len(pns) - limit} more" if len(pns) > limit else "")


def change_text(change):
    """The question before a project is changed or deleted (`change` is a project_admin.ProjectChange)."""
    if change.deleting:
        lines = [f"Delete project {change.old.describe()}?", ""]
        lines.append(f"{len(change.leaving)} part{'s' if len(change.leaving) != 1 else ''} will have no project"
                     + (f": {_some(change.leaving)}." if change.leaving else "."))
        lines += ["", "Its part numbers are freed: New Part with no project may then use them."]
    else:
        lines = [f"Change project {change.old.describe()} to {change.new.describe()}?", ""]
        if change.new.prefix != change.old.prefix:
            lines.append("This changes which parts are in the project.")
        for pns, many, one in ((change.joining, "parts join the project", "part joins the project"),
                               (change.leaving, "parts leave it (no project)", "part leaves it (no project)"),
                               (change.renamed, f"parts are renamed to {change.new.name}",
                                f"part is renamed to {change.new.name}")):
            if pns:
                lines.append(f"{len(pns)} {many if len(pns) != 1 else one}: {_some(pns)}.")
        if not change.updates:
            lines.append("No parts change.")
    if change.updates:
        lines += ["", f"Their records are changed in one upload ({len(change.updates)} record"
                      f"{'s' if len(change.updates) != 1 else ''}), and each part's history says so."]
    return "\n".join(lines)
