"""
export_text.py - Export Files and Export BOM in words: the folder offered first, the question before replacing
files, and what the status line says afterwards (see exporting/).
"""

from pathlib import Path

SETTING = "export_folder"           # settings.yaml: the folder the last export went to


def start_folder(settings_data, home=None):
    """The folder the window offers first: the last one used, if it is still there, else your home folder."""
    last = str((settings_data or {}).get(SETTING) or "")
    if last and Path(last).is_dir():
        return last
    return str(home if home is not None else Path.home())


def replace_question(folder, names):
    shown = "\n".join(f"  {name}" for name in names[:8]) + ("\n  ..." if len(names) > 8 else "")
    return (f"{folder} already has {len(names)} of these files:\n\n{shown}\n\nReplace them with the copies from "
            "the vault?")


def plan_lines(export_plan):
    """What the window says about a plan before copying: how many files, and its notes."""
    count = len(export_plan.files)
    return [f"{count} file{'s' if count != 1 else ''} to copy."] + list(export_plan.notes)


def exported_text(folder, names):
    count = len(names)
    return f"Exported {count} file{'s' if count != 1 else ''} to {folder}."
