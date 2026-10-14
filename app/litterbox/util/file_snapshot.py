"""
file_snapshot.py - noticing that a file was saved after you pressed Check In.

Check In now runs in the background, so there can be a wait between the click and the moment Litterbox reads the
files. If you save a part in SolidWorks during that wait, what gets uploaded might not be what you meant, or a file
might be half written when Litterbox reads it. Litterbox does not stop the save (that would mean changing the
files' read-only state under SolidWorks); it notices, and refuses to upload that part. The part stays checked out
to you and nothing is lost: save, then Check In again.

How: at the click, remember each file's size and modified time (a metadata lookup, microseconds; the file's
contents are never read). Before uploading, look again. Two details keep it honest:

* Litterbox's own downloads (`git pull --autostash`) can rewrite your modified files with identical contents, which
  changes their modified time. So just before every pull we compare, and just after it we take the new times as the
  baseline. A real save before the pull is still caught; one in the few seconds of the pull itself is not.
* Just before Litterbox hands a part's files to git, and again after, it compares the times (see `stats` and
  `moved`), which catches a save in the middle of the upload. That needs no snapshot.
"""

import os
import threading
from pathlib import Path

_LOCK = threading.Lock()
_ACTIVE = []                        # snapshots whose job has not finished yet


def stat_of(repo, relpath):
    """(size, modified time in nanoseconds) of a file, or None if it is not there."""
    try:
        st = os.stat(Path(repo) / relpath)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def stats(repo, relpaths):
    return {rel: stat_of(repo, rel) for rel in relpaths}


def moved(repo, before):
    """The files in `before` ({path: stat}) that are now different."""
    return [rel for rel, old in before.items() if stat_of(repo, rel) != old]


def names(relpaths):
    return ", ".join(sorted(Path(rel).name for rel in relpaths))


class FileSnapshot:
    def __init__(self, repo, files_by_pn):
        self.repo = str(repo)
        self.files = {str(pn): tuple(files) for pn, files in files_by_pn.items()}
        self.baseline = stats(repo, [rel for files in self.files.values() for rel in files])
        self.changed = set()        # files seen to change before a pull (stays set)
        with _LOCK:
            _ACTIVE.append(self)

    def covers(self, pn):
        return str(pn) in self.files

    def problems(self, pn, current_files):
        """The files of this part that were saved, removed or added since the snapshot."""
        found = []
        with _LOCK:
            for rel in sorted(set(self.files.get(str(pn), ())) | set(current_files)):
                if rel in self.changed or rel not in self.baseline or stat_of(self.repo, rel) != self.baseline[rel]:
                    found.append(rel)
        return found

    def release(self):
        with _LOCK:
            if self in _ACTIVE:
                _ACTIVE.remove(self)


def before_pull(repo):
    """Called just before a download: remember which watched files were already changed by you."""
    with _LOCK:
        for snap in _ACTIVE:
            if snap.repo == str(repo):
                for rel, old in snap.baseline.items():
                    if rel not in snap.changed and stat_of(snap.repo, rel) != old:
                        snap.changed.add(rel)


def after_pull(repo):
    """Called just after a download: git may have rewritten your files with the same contents, so take their
    times as they are now (except files already seen to change)."""
    with _LOCK:
        for snap in _ACTIVE:
            if snap.repo == str(repo):
                for rel in snap.baseline:
                    if rel not in snap.changed:
                        snap.baseline[rel] = stat_of(snap.repo, rel)
