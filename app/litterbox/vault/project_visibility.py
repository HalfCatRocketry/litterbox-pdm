"""
project_visibility.py - hidden projects (core/projects.py): their parts are left out of the copy of everyone who
may not see them (team/project_access.py may_see), so Litterbox never shows them and never downloads their files.

A project's parts are every part number in its block, so the files to leave out follow from its digits:
    PN-logs/HCR-12*                  its records
    cad/HCR-12*                      their CAD files, STEPs, PDFs and saved BOMs
    cancelled-revs/CANCELLED_HCR-12* their cancelled revisions
apply() runs at Get Latest, when a vault is opened and after a project changes. Someone added to a hidden project
gets its parts at their next Get Latest; someone taken off loses them then.

These checks are process control, not security: anyone with access to the vault's host can read all of it.
"""

from litterbox import diagnostics
from litterbox import layout
from litterbox.errors import LitterboxError
from litterbox.git import sparse
from litterbox.team import project_access
from litterbox.team import team_identity
from litterbox.vault import config


def patterns(org, projects):
    """The paths to leave out for these (hidden) projects."""
    found = []
    for project in projects:
        start = f"{org}-{project.prefix}"
        found += [f"/{layout.LOG_DIR_NAME}/{start}*", f"/{layout.CAD_DIR_NAME}/{start}*",
                  f"/{layout.CANCELLED_DIR_NAME}/{layout.CANCELLED_PREFIX}{start}*"]
    return found


def hidden_from(identity, projects):
    """The hidden projects this person (an Identity) may not see. Someone the team doesn't know sees none."""
    if identity.state == team_identity.LEGACY:
        return []
    person = identity.person if identity.state == team_identity.OK else None
    return [p for p in projects if p.hidden and not project_access.may_see(person, p)]


def apply(repo, identity=None):
    """Leave the hidden projects' parts out of this copy, for the current user. Returns True if the copy changed.
    Never raises: a problem is logged and the copy is left as it was."""
    try:
        config.apply(repo)                                  # this vault's digits, to read its part numbers
        projects = config.get_projects(repo)
        if not any(p.hidden for p in projects) and not sparse.excluded(repo):
            return False                                    # the usual case: nothing hidden, nothing to undo
        if identity is None:
            identity = team_identity.current(repo)          # remembered for a day; asks the host if not known
        return sparse.set_excluded(repo, patterns(_org(repo), hidden_from(identity, projects)))
    except (LitterboxError, config.ConfigError, OSError) as e:
        diagnostics.LOG(f"WARNING: could not bring the hidden projects up to date in this copy: {e}")
        return False


def _org(repo):
    """The vault's org code. A vault whose settings don't name it has it read from the part records; when they are
    all left out, the patterns already in place still say it."""
    try:
        return config.get_org(repo)
    except config.ConfigError:
        start = f"/{layout.LOG_DIR_NAME}/"
        for pattern in sparse.excluded(repo):
            if pattern.startswith(start) and "-" in pattern:
                return pattern[len(start):].split("-", 1)[0]
        raise


def shown_ecos(repo, ecos):
    """The ECOs to list: all of them, less those whose parts are all left out of this copy (a hidden project's)."""
    try:
        if not sparse.excluded(repo):
            return list(ecos)
    except (LitterboxError, OSError):
        return list(ecos)
    left_out = [p.lstrip("/").rstrip("*") for p in sparse.excluded(repo) if p.startswith(f"/{layout.LOG_DIR_NAME}/")]
    starts = [p.split("/", 1)[1] for p in left_out]
    return [eco for eco in ecos
            if not eco.parts or not all(any(str(part.get("pn", "")).startswith(s) for s in starts)
                                        for part in eco.parts)]
