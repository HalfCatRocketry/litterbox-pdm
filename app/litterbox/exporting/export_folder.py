"""
export_folder.py - where an export may go: a folder outside Litterbox's own folder (C:\\Litterbox) and outside
every git repository, so a copy can never be committed, locked or mistaken for a vault file.
"""

import os
from pathlib import Path

from litterbox.errors import LitterboxError


class ExportError(LitterboxError):
    """An export can't go ahead. The message is safe to show."""


def _same_or_inside(path, folder):
    path, folder = os.path.normcase(str(path)), os.path.normcase(str(folder))
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def repository_around(folder):
    """The git repository this folder is in (the folder holding .git), or None."""
    for place in (folder, *folder.parents):
        if (place / ".git").exists():
            return place
    return None


def check(folder, litterbox_root):
    """The folder, made absolute, if an export may go there. Raises ExportError saying why not."""
    if not str(folder or "").strip():
        raise ExportError("Choose a folder to export to.")
    folder = Path(folder).expanduser()
    try:
        folder = folder.resolve()
    except OSError as e:
        raise ExportError(f"That folder can't be used: {e}") from None
    if not folder.is_dir():
        raise ExportError(f"There is no folder {folder}.")
    root = Path(litterbox_root).resolve()
    if _same_or_inside(folder, root):
        raise ExportError(f"Choose a folder outside {root}. Litterbox keeps its vaults there, and a copy inside "
                          "could end up uploaded or locked like a vault file.")
    repo = repository_around(folder)
    if repo is not None:
        raise ExportError(f"Choose a folder outside {repo}: it is a git repository, and a copy inside could end up "
                          "committed with it.")
    return folder
