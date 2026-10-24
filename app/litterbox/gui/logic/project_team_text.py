"""
project_team_text.py - the Project window's people: who may be the Lead, who can be added as a member (searched by
name, id or email), the members list, and the line each project shows in the Projects list about its Lead, members,
Restrict and Hide. The rules are core/projects.py's and team/project_access.py's.
"""

from litterbox.gui.logic import task_text

NO_LEAD = "No Lead"

RESTRICT_TEXT = "Restrict Project"
RESTRICT_NOTE = ("Only its members, its Lead, Admins and the Owner may make its part numbers, change its parts, and "
                 "ask for or sign its workflows.")
HIDE_TEXT = "Hide Project"
LEAD_FOLDERS_TEXT = "Only the Lead changes its folders"
LEAD_FOLDERS_NOTE = ("Each member sees the project's folders in Home. Unticked, any member can change them; ticked, "
                     "only the Lead (and Admins and the Owner).")
HIDE_NOTE = ("Restricted, and nobody else sees it or its parts at all: Litterbox leaves them out of their copy of "
             "the vault.")
NEEDS_LEAD = "Choose a Project Lead first: a restricted or hidden project needs one."


def _label(person):
    return person.name + ("" if person.active else " (switched off)")


def lead_choices(directory, current=""):
    """[(label, id)] for the Lead's menu: the team's active people, and the current Lead even if switched off."""
    people = [p for p in directory.people if p.active or p.id == current]
    return task_text.person_labels(people)


def lead_label(choices, lead):
    """What the Lead's menu shows for this Lead id."""
    return next((label for label, pid in choices if pid == lead), NO_LEAD)


def matches(person, search):
    wanted = " ".join(str(search or "").lower().split())
    if not wanted:
        return True
    text = " ".join([person.name, person.id, getattr(person, "email", "") or ""]).lower()
    return all(word in text for word in wanted.split())


def addable(directory, lead, members, search=""):
    """[(label, id)] of the active people who could be added: not the Lead, not a member, matching the search."""
    taken = set(members) | {lead}
    people = [p for p in directory.people if p.active and p.id not in taken and matches(p, search)]
    return task_text.person_labels(people)


def member_rows(directory, members):
    """[(label, id)] of the members, in the order they were added; someone no longer on the team shows their id."""
    rows = []
    for person_id in members:
        person = directory.get(person_id) if directory is not None else None
        rows.append((_label(person) if person else person_id, person_id))
    return rows


def team_line(directory, project):
    """'Lead: Alex Smith · 3 members · Hidden', or '' for a project with none of them."""
    parts = []
    if project.lead:
        person = directory.get(project.lead) if directory is not None else None
        parts.append(f"Lead: {person.name if person else project.lead}")
    if project.members:
        parts.append(f"{len(project.members)} member{'s' if len(project.members) != 1 else ''}")
    if project.hidden:
        parts.append("Hidden")
    elif project.restricted:
        parts.append("Restricted")
    return " · ".join(parts)


def problem(lead, restricted, hidden):
    """Why the window's choices can't be saved ('' when they can)."""
    return NEEDS_LEAD if (restricted or hidden) and not lead else ""
