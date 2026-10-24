"""
toolbox_rules.py - the team's rule for SolidWorks Toolbox parts (the vault setting `toolbox`, Team > Vault
Settings), and what it says about the files an assembly uses that aren't Litterbox parts. Pure rules: the files are
read at check-in and by Update BOM (references/reference_reader.py) and kept in the record
(records/record_other_files.py); Check In and Release refuse an assembly this finds problems with.

    OFF          "" (the default, and every vault made before 0.6.0): nothing is checked
    NO_TOOLBOX   "none": no Toolbox parts, and no files from outside the vault
    TEAM         "team": Toolbox parts only from the team's Toolbox, kept in the vault's toolbox/ folder by an
                 Admin (vault/toolbox_admin.py); no other files from outside the vault

Each file an assembly uses is an entry {"file": path, "toolbox": True if it is a Toolbox part}. A file inside the
vault is written relative to it with forward slashes ("toolbox/browser/.../screw.sldprt"); one outside it as the
CAD program found it ("C:\\SOLIDWORKS Data\\browser\\...\\screw.sldprt").
"""

import ntpath
import posixpath

OFF, NO_TOOLBOX, TEAM = "", "none", "team"
RULES = (OFF, NO_TOOLBOX, TEAM)

LABELS = {
    OFF: "Don't check",
    NO_TOOLBOX: "No Toolbox parts",
    TEAM: "Only the team's Toolbox",
}

MIN_LITTERBOX = "0.6.0"          # the first Litterbox that checks assemblies against a rule

SHOWN = 5                       # how many files a problem names before "and 3 more"


class ToolboxRuleError(ValueError):
    pass


def check(value):
    """A rule from the settings, checked: None and "" are OFF. Raises ToolboxRuleError."""
    value = "" if value is None else str(value).strip().lower()
    if value not in RULES:
        raise ToolboxRuleError(f"The Toolbox rule must be one of {', '.join(repr(r) for r in RULES)}, not {value!r}.")
    return value


def in_vault(file):
    """True for an entry's file inside the vault (written relative to it), False for one outside it."""
    return not (ntpath.isabs(file) or posixpath.isabs(file) or ntpath.splitdrive(file)[0])


def in_team_toolbox(file, folder):
    """True if a vault-relative file is inside the team's Toolbox folder (layout.TOOLBOX_DIR_NAME)."""
    return in_vault(file) and file.replace("\\", "/").lower().startswith(folder.lower().rstrip("/") + "/")


def _names(files):
    names = sorted({ntpath.basename(f.replace("/", "\\")) for f in files}, key=str.lower)
    shown = ", ".join(names[:SHOWN])
    return shown + (f" and {len(names) - SHOWN} more" if len(names) > SHOWN else "")


def _folders(files):
    folders = sorted({ntpath.dirname(f.replace("/", "\\")) for f in files if not in_vault(f)}, key=str.lower)
    return ", ".join(folders[:2]) + (" and others" if len(folders) > 2 else "")


def problems(rule, entries, folder="toolbox", toolbox_path=""):
    """What breaks the rule among an assembly revision's entries, as sentences ([] if nothing does). `folder` is the
    team's Toolbox folder in the vault and `toolbox_path` the same on this computer, for the advice."""
    if rule == OFF:
        return []
    toolbox = [e["file"] for e in entries if e.get("toolbox")]
    outside = [e["file"] for e in entries if not e.get("toolbox") and not in_vault(e["file"])]
    found = []
    if rule == NO_TOOLBOX and toolbox:
        found.append(f"It uses Toolbox parts ({_names(toolbox)}). This team doesn't use Toolbox: model each "
                     "fastener as a part of its own in Litterbox, and use that instead.")
    if rule == TEAM:
        wrong = [f for f in toolbox if not in_team_toolbox(f, folder)]
        if wrong:
            where = f" at {toolbox_path}" if toolbox_path else ""
            found.append(f"It uses Toolbox parts that aren't from the team's Toolbox ({_names(wrong)}, from "
                         f"{_folders(wrong) or 'another folder'}). SolidWorks takes Toolbox parts from the Toolbox "
                         f"it is set to use: set it to the team's{where} (Tools > Options > System Options > Hole "
                         "Wizard/Toolbox), then open the assembly again and check it in.")
    if outside:
        found.append(f"It uses files from outside the vault ({_names(outside)}, in {_folders(outside)}). Nobody else "
                     "has them: add them to Litterbox as parts and use those instead.")
    return found
