"""
import_paths.py - small helpers for the source files' paths: comparing them, extensions, folders,
and a size/time snapshot to notice a file that changed during the import.
"""

import os
from pathlib import Path


def path_key(path):
    return os.path.normcase(os.path.abspath(path))


def ext_of(path):
    return os.path.splitext(path)[1].lower()


def is_inside(path, folder):
    folder = path_key(folder).rstrip("\\/") + os.sep
    return path_key(path).startswith(folder)


def relative_path(repo, path):
    return Path(os.path.relpath(path, repo)).as_posix()


def snapshot_files(paths):
    result = {}
    for path in paths:
        try:
            st = os.stat(path)
            result[path] = (st.st_size, st.st_mtime_ns)
        except OSError:
            result[path] = None
    return result
