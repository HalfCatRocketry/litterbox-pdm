"""
solidworks_watch.py - what the main window does with the SolidWorks watcher (cad/solidworks/sw_watcher.py), when
settings.yaml has `solidworks_watch: true`: ask before checking in parts with unsaved changes in SolidWorks, warn
before Get Latest replaces files that are open there, and warn when a part waiting to be checked in is opened or
saved. With `solidworks_popups: false` the warnings go to the log and the status line instead, and nothing is asked.
"""

from tkinter import messagebox

from litterbox.cad.solidworks import sw_watcher
from litterbox.gui.logic import solidworks_text
from litterbox.user import settings


class SolidWorksWatch:
    """What SolidWorks has open, and what Litterbox does about it (part of the main window, App)."""

    sw_watcher = None

    def _start_solidworks_watcher(self):
        if not settings.solidworks_watch(self.settings):
            return
        self.sw_watcher = sw_watcher.SolidWorksWatcher(on_change=lambda changes: self.queue.put(("solidworks", changes)))
        self.sw_watcher.start()
        self._log("Watching what SolidWorks has open (solidworks_watch in settings.yaml).")

    def _stop_solidworks_watcher(self):
        if self.sw_watcher is not None:
            self.sw_watcher.stop()
            self.sw_watcher = None

    def _solidworks_popups(self):
        return settings.solidworks_popups(getattr(self, "settings", {}))

    def _solidworks_snapshot(self):
        return self.sw_watcher.snapshot() if self.sw_watcher is not None else None

    def _solidworks_changed(self, changes):
        """Called on the window's thread with the watcher's changes."""
        busy = self.jobs.pending_parts()
        if not busy:
            return
        by_text = {str(pn): row for pn, row in self.rows_by_pn.items()}
        notes = solidworks_text.queued_part_notes(
            changes, self.repo(), busy,
            lambda pn: [f for files in getattr(by_text.get(pn), "revisions", {}).values() for f in files])
        for note in notes:
            self._log("WARNING: " + note)
            if self._solidworks_popups():
                messagebox.showwarning("Litterbox is still working", note, parent=self)
            else:
                self._say(note, "warn")

    def _saved_in_solidworks(self, files, action):
        """Before Check In / Save Progress: True to go ahead. Asks if any of these have unsaved changes."""
        snapshot = self._solidworks_snapshot()
        if snapshot is None:
            return True
        unsaved = solidworks_text.unsaved_among(snapshot, self.repo(), files)
        if not unsaved:
            return True
        if not self._solidworks_popups():
            self._log("WARNING: not saved in SolidWorks yet: " + ", ".join(unsaved))
            return True
        return messagebox.askyesno("Not saved in SolidWorks", solidworks_text.save_first_question(unsaved, action),
                                   parent=self)

    def _closed_in_solidworks(self, files):
        """Before Get Latest: True to go ahead. Asks if any of these files are open in SolidWorks."""
        snapshot = self._solidworks_snapshot()
        if snapshot is None:
            return True
        still_open = solidworks_text.open_among(snapshot, self.repo(), files)
        if not still_open:
            return True
        if not self._solidworks_popups():
            self._log("WARNING: open in SolidWorks during Get Latest: " + ", ".join(still_open))
            return True
        return messagebox.askyesno("Open in SolidWorks", solidworks_text.may_be_replaced_question(still_open),
                                   parent=self)

    def _open_in_solidworks(self, files):
        """The files among these that SolidWorks has open, or None if Litterbox isn't watching."""
        snapshot = self._solidworks_snapshot()
        return None if snapshot is None else solidworks_text.open_among(snapshot, self.repo(), files)
