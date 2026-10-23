"""
toolbox_check.py - holding assemblies to the team's Toolbox rule (core/toolbox_rules.py, the vault setting `toolbox`):
Check In refuses an assembly whose SolidWorks file breaks it, and Release (parts/planning.py) refuses an assembly
revision that breaks it or hasn't been read since it last changed (records/record_other_files.py).

With the rule TEAM, a Toolbox part must also be one the team's Toolbox in the vault already has: one SolidWorks has
just made there (a new size) is on this computer only until an Admin uploads it (vault/toolbox_admin.py).
"""

from pathlib import Path

from litterbox import layout
from litterbox.core import file_types
from litterbox.core import toolbox_rules
from litterbox.git import repository
from litterbox.records import record_other_files
from litterbox.vault import config


def rule(repo):
    return config.get_toolbox_rule(repo)


def toolbox_path(repo):
    """The team's Toolbox folder on this computer."""
    return str(Path(repo) / layout.TOOLBOX_DIR_NAME)


def uploaded_toolbox_files(repo):
    """The team's Toolbox files git has, in lower case (paths relative to the vault)."""
    return {rel.lower() for rel in repository.tracked(repo, layout.TOOLBOX_DIR_NAME)}


def problems(repo, entries, rule_now=None):
    """What breaks the team's rule among an assembly's entries ([{file, toolbox}]), as sentences."""
    rule_now = rule(repo) if rule_now is None else rule_now
    found = toolbox_rules.problems(rule_now, entries, layout.TOOLBOX_DIR_NAME, toolbox_path(repo))
    if rule_now == toolbox_rules.TEAM:
        team = [e["file"] for e in entries
                if e.get("toolbox") and toolbox_rules.in_team_toolbox(e["file"], layout.TOOLBOX_DIR_NAME)]
        uploaded = uploaded_toolbox_files(repo) if team else set()
        new = [f for f in team if f.lower() not in uploaded]
        if new:
            names = ", ".join(sorted({file_types.file_name(f) for f in new}, key=str.lower))
            found.append(f"It uses Toolbox parts that are on this computer but not in the team's Toolbox yet ({names}). "
                         "An Admin needs to upload them first (Team > Toolbox...).")
    return found


def check_in_problem(repo, pn, entries):
    """Why Check In refuses this assembly, or "" if it doesn't. `entries` None: SolidWorks couldn't read it, so
    there is nothing to check now (Release asks for Update BOM)."""
    if entries is None:
        return ""
    found = problems(repo, entries)
    if not found:
        return ""
    return (f"{pn} was not checked in. " + " ".join(found) + " It is still checked out to you.")


def release_problems(repo, record, revision, files, rule_now=None):
    """Why this assembly revision can't be released under the team's rule ([] if it can). `files` are the
    revision's files: only a revision with an assembly file is checked."""
    rule_now = rule(repo) if rule_now is None else rule_now
    if rule_now == toolbox_rules.OFF or record.cots or not any(file_types.is_assembly(f) for f in files):
        return []
    if not record_other_files.is_read(record, revision):
        return ["Litterbox hasn't checked it for Toolbox parts since it last changed. Use Update BOM on its BOM tab "
                "(SolidWorks reads it), then release it."]
    return problems(repo, record_other_files.entries(record, revision), rule_now)
