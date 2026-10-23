"""
toolbox_text.py - what Team > Toolbox... says about the team's SolidWorks Toolbox (vault/toolbox_admin.py): the
rule, the folder, whether this computer's SolidWorks uses it, and changes not uploaded yet; and the warning after a
refresh when this computer's SolidWorks uses another Toolbox.
"""

from litterbox.core import toolbox_rules

SOLIDWORKS_SETTING = "Tools > Options > System Options > Hole Wizard/Toolbox"


def _files(n):
    return f"{n:,} file{'' if n == 1 else 's'}"


def rule_line(rule):
    return {
        toolbox_rules.OFF: "The rule: none. Assemblies aren't checked for Toolbox parts (Team > Vault Settings...).",
        toolbox_rules.NO_TOOLBOX: "The rule: no Toolbox parts. Assemblies may not use Toolbox parts, so the team's "
                                  "Toolbox isn't used.",
        toolbox_rules.TEAM: "The rule: only the team's Toolbox. Assemblies may use Toolbox parts from it, and from "
                            "nowhere else.",
    }.get(rule, "")


def changes_text(changes):
    """'3 files added, 1 changed' for Status.changes ({kind: [rel]})."""
    parts = []
    for kind in ("added", "changed", "removed"):
        n = len(changes.get(kind, []))
        if n:
            parts.append(f"{_files(n)} {kind}" if not parts else f"{n:,} {kind}")
    return ", ".join(parts)


def status_lines(status, admin):
    """The lines Team > Toolbox... shows. status: a toolbox_admin.Status; admin: may this person change it?"""
    lines = [rule_line(status.rule), ""]
    if status.files:
        downloaded = f" ({status.not_downloaded:,} not downloaded yet)" if status.not_downloaded else ""
        lines.append(f"The team's Toolbox: {_files(status.files)} in {status.folder}{downloaded}.")
    else:
        lines.append("The vault has no Toolbox yet." + (" Copy one in with Copy in a Toolbox folder..." if admin
                                                         else " An Admin or the Owner copies one in."))
    if status.solidworks_uses_it:
        lines.append("This computer's SolidWorks uses it.")
    elif status.solidworks_folder:
        lines.append(f"This computer's SolidWorks uses another Toolbox: {status.solidworks_folder}. To use the team's, "
                     f"set the Toolbox folder in SolidWorks ({SOLIDWORKS_SETTING}) to {status.folder}.")
    else:
        lines.append(f"Litterbox can't tell which Toolbox this computer's SolidWorks uses. Its folder is set in "
                     f"SolidWorks: {SOLIDWORKS_SETTING}.")
    if status.has_changes:
        lines += ["", f"Changed on this computer and not uploaded yet: {changes_text(status.changes)}."
                  + (" Upload them with Upload changes." if admin
                     else " Only an Admin or the Owner can upload changes to the team's Toolbox.")]
    if admin:
        lines += ["", "Its files are read-only for everyone. To add sizes or change its settings in SolidWorks, press "
                      "Let me change it first, then Upload changes. Set Toolbox to make a file for each size (Toolbox "
                      "Settings > User Settings > Create Parts), so a new size is a new file."]
    return lines


JOB_LABELS = {"download": "Downloading the team's Toolbox", "copy_in": "Copying in the team's Toolbox",
              "open": "Making the team's Toolbox changeable", "upload": "Uploading the team's Toolbox"}


def copy_in_question(folder, status):
    """The question before an Admin copies a Toolbox folder in as the team's."""
    replaces = (f" It replaces the team's Toolbox ({_files(status.files)}): files it doesn't have are removed."
                if status.files else "")
    return (f"Make {folder} the team's Toolbox?{replaces}\n\nIt is copied into {status.folder} and uploaded for "
            "everyone (a whole Toolbox is several hundred MB, so this takes a while). Everyone's copy of it is "
            "read-only.\n\nCopy it in?")


def done_text(action, result):
    """The status line after an action of the Toolbox window."""
    if action == "download":
        return f"Downloaded {_files(result)} of the team's Toolbox" if result else "The team's Toolbox is downloaded"
    if action == "open":
        return f"The team's Toolbox can be changed on this computer ({_files(result)}). Upload changes when done."
    if any(result.values()):
        return "Team's Toolbox uploaded: " + changes_text({k: [None] * n for k, n in result.items()})
    return "The team's Toolbox has no changes to upload"


def not_downloaded_warning(count):
    """After a refresh, once a session: this computer's SolidWorks uses the team's Toolbox, but not all of it is here."""
    it = "it" if count == 1 else "them"
    return (f"{_files(count)} of the team's Toolbox {'is' if count == 1 else 'are'} not downloaded yet, so SolidWorks "
            f"can't use {it}. Download {it} in Team > Toolbox....")


def other_toolbox_warning(solidworks_folder, team_folder):
    """After a refresh, once a session, with the rule TEAM: this computer's SolidWorks uses another Toolbox."""
    return (f"Your SolidWorks uses the Toolbox in {solidworks_folder}, not the team's ({team_folder}). Assemblies with "
            f"Toolbox parts from it can't be checked in. Set it in SolidWorks: {SOLIDWORKS_SETTING}.")
