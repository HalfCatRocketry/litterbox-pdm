"""
export_text.py - Export Files and Export BOM in words: the folder offered first, the revisions Export Files offers,
the question before replacing files, and what the status line says afterwards (see exporting/).
"""

from pathlib import Path

from litterbox.exporting import part_files_export

SETTING = "export_folder"           # settings.yaml: the folder the last export went to


def start_folder(settings_data, home=None):
    """The folder the window offers first: the last one used, if it is still there, else your home folder."""
    last = str((settings_data or {}).get(SETTING) or "")
    if last and Path(last).is_dir():
        return last
    return str(home if home is not None else Path.home())


def revision_choices(rows):
    """([(label, which)], the label chosen first) for Export Files' Revision list. `which` is RELEASED, WORKING or a
    revision letter. One part lists its working revision, then every released one, newest first, the latest
    marked; several parts (whose letters differ) get Latest released and Working."""
    latest_text = "Latest released"
    if len(rows) != 1:
        return [(latest_text, part_files_export.RELEASED), ("Working", part_files_export.WORKING)], latest_text
    row = rows[0]
    latest = row.released_revision
    working_is_latest = row.record_status == "released" and row.revision == latest
    choices = [] if working_is_latest else [(f"Working (Rev {row.revision})", part_files_export.WORKING)]
    for rev in reversed(tuple(row.released_revisions)):
        if rev == row.revision and not working_is_latest:
            continue                    # released once, but reopened since: the working entry covers it
        choices.append((f"Rev {rev} ({latest_text})" if rev == latest else f"Rev {rev}", rev))
    if not choices:
        choices = [(f"Working (Rev {row.revision})", part_files_export.WORKING)]
    first = next((label for label, which in choices if which == latest), choices[0][0])
    return choices, first


def replace_question(folder, names, replacement="the copies from the vault"):
    shown = "\n".join(f"  {name}" for name in names[:8]) + ("\n  ..." if len(names) > 8 else "")
    return f"{folder} already has {len(names)} of these files:\n\n{shown}\n\nReplace them with {replacement}?"


def plan_lines(export_plan):
    """What the window says about a plan before copying: how many files, and its notes."""
    count = len(export_plan.files)
    return [f"{count} file{'s' if count != 1 else ''} to copy."] + list(export_plan.notes)


def exported_text(folder, names):
    count = len(names)
    return f"Exported {count} file{'s' if count != 1 else ''} to {folder}."
