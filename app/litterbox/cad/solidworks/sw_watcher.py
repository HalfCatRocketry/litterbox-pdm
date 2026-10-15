"""
sw_watcher.py - keeps an eye on what SolidWorks has open, in the background.

A thread asks the running SolidWorks every few seconds which documents are open, unsaved or read-only (see
sw_documents.py), keeps the latest answer (snapshot), and tells on_change about every difference. It only reads:
it never starts SolidWorks, and if SolidWorks isn't running the snapshot is simply empty. In debug mode every
change is logged, so it can be checked against what you see in SolidWorks.

    watcher = SolidWorksWatcher(on_change=lambda changes: ...)
    watcher.start()
    watcher.snapshot()          # {key(path): OpenDocument}
    watcher.stop()

Switched on by `solidworks_watch: true` in settings.yaml (see user/settings.py).
"""

import threading

from litterbox import diagnostics
from litterbox.cad.solidworks import com
from litterbox.cad.solidworks import sw_documents

POLL_SECONDS = 3.0


class Change:
    """One difference between two snapshots: what happened to which file."""
    OPENED, CLOSED, MODIFIED, SAVED = "opened", "closed", "has unsaved changes", "saved"

    def __init__(self, what, document):
        self.what = what
        self.document = document

    @property
    def key(self):
        return sw_documents.key(self.document.path)

    def __repr__(self):
        return f"Change({self.what!r}, {self.document.path!r})"


def differences(old, new):
    """[Change] between two snapshots, in a steady order."""
    changes = []
    for k in sorted(set(old) | set(new)):
        before, after = old.get(k), new.get(k)
        if before is None:
            changes.append(Change(Change.OPENED, after))
        elif after is None:
            changes.append(Change(Change.CLOSED, before))
        elif after.unsaved and not before.unsaved:
            changes.append(Change(Change.MODIFIED, after))
        elif before.unsaved and not after.unsaved:
            changes.append(Change(Change.SAVED, after))
    return changes


class SolidWorksWatcher:
    def __init__(self, on_change=None, attach=sw_documents.attach, read=sw_documents.open_documents,
                 interval=POLL_SECONDS):
        self.on_change = on_change
        self._attach, self._read, self.interval = attach, read, interval
        self._sw = None
        self._snapshot = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._complained = False

    def snapshot(self):
        """{key(path): OpenDocument} as of the last look."""
        with self._lock:
            return dict(self._snapshot)

    def is_open(self, path):
        return sw_documents.key(path) in self.snapshot()

    def poll_once(self):
        """Look once (on the calling thread, which must have COM switched on). Returns the changes."""
        try:
            if self._sw is None:
                self._sw = self._attach()
            new = self._read(self._sw) if self._sw is not None else {}
            self._complained = False
        except Exception as e:                          # SolidWorks closed, or busy: start again next time
            self._sw = None
            if not self._complained:
                diagnostics.LOG(f"SolidWorks watcher: could not ask SolidWorks what is open ({e}). Trying again.")
                self._complained = True
            new = {}
        with self._lock:
            old, self._snapshot = self._snapshot, new
        changes = differences(old, new)
        if changes and diagnostics.DEBUG:
            for change in changes:
                diagnostics.LOG(f"SolidWorks: {change.what}: {change.document.path}"
                                + (" (read-only)" if change.document.read_only else ""))
        if changes and self.on_change:
            self.on_change(changes)
        return changes

    def _run(self):
        with com.com_thread():
            while not self._stop.is_set():
                self.poll_once()
                self._stop.wait(self.interval)
            self._sw = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="SolidWorks watcher", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2 * self.interval)
            self._thread = None
