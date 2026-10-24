"""
personal_folders.py - your Personal folders, kept on this computer only (one file per org, outside the vault, so
nobody else sees them and they never go up with an upload). The window chooses the file:
C:\\Litterbox\\folders\\<org>.yaml.

    tree = personal_folders.load(path)          # {} if there's no file yet, or it can't be read
    personal_folders.save(path, tree)

The file is the changes that build the tree (folders/folder_model.to_ops), so it reads like the vault's folder
changes. Kept on one computer for now (REMINDERS.md: Personal folders), so a new computer starts with none.
"""

from pathlib import Path

import yaml

from litterbox import diagnostics
from litterbox.folders import folder_model
from litterbox.util import fast_yaml

VERSION = 1


def load(path):
    """The Personal tree in `path` ({} without one; a file that can't be read is logged and left alone)."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = fast_yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        diagnostics.LOG(f"WARNING: your Personal folders ({path}) can't be read: {e}")
        return {}
    ops = data.get("folders") if isinstance(data, dict) else None
    return folder_model.build(op for op in ops or [] if isinstance(op, dict))


def save(path, tree):
    """Write the Personal tree to `path`. Raises OSError if it can't be written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump({"version": VERSION, "folders": folder_model.to_ops(tree)}, f, sort_keys=False,
                       allow_unicode=True)
    temporary.replace(path)
