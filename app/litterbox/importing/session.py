"""
session.py - runs an import for the window, with no window code in it.

The Import window (gui/windows/import_window) talks only to an ImportSession. All the slow work (scanning,
reading references, copying, committing) happens on ONE background thread that lives as long
as the session. One thread matters: SolidWorks is reached through COM, and COM objects must
stay on the thread that made them.

    session = ImportSession(repo, post)       post(fn) runs fn on the window's thread
    session.start(on_done, on_progress, folders=[...])        scan the folders, then prepare
    session.start(on_done, on_progress, manifest_path="...")  or prepare an existing manifest
    session.scan(on_done, on_progress, folders=[...])         only scan (the window can ask about what it found),
    session.start(on_done, on_progress, scanned=manifest)     then save that scan and prepare it
    session.include(item_id, True, on_done)    tick / untick a row
    session.set_family(base, on_done)          import all as variants of one base number (None: undo)
    session.refresh(on_done)                   check the numbers against the newest records
    session.finish(on_done, on_progress)       Finish & Import
    session.cancel()                           stop whatever is running; nothing is left behind
    session.close()

on_done(result, error) is called on the window's thread; `error` is the exception (or None), so
the window can tell import_errors.PNConflict and import_errors.ImportCancelled from other failures.
While a job runs, session.busy is True and the table must not be edited (the worker is using it).
"""

import queue
import threading
from datetime import datetime
from pathlib import Path

from litterbox.cad import cad_programs
from litterbox.importing import import_duplicates
from litterbox.importing import import_errors
from litterbox.importing import import_finish
from litterbox.importing import import_numbering
from litterbox.importing import import_prepare
from litterbox.importing import manifest as manifest_module
from litterbox.importing import scan
from litterbox.core import part_number
from litterbox.parts import create
from litterbox.parts import create_batch
from litterbox.vault import config


def default_manifest_path(root, now=None):
    """Where a new scan's manifest is kept: <root>/imports/import-20261009-210700.yaml"""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return Path(root) / "imports" / f"import-{stamp}.yaml"


class ImportSession:
    def __init__(self, repo, post, backend_factory=None, log=lambda text: None, org=None,
                 gap=import_numbering.DEFAULT_GAP, jitter=import_numbering.DEFAULT_JITTER):
        self.repo, self.post, self.log, self.org = repo, post, log, org
        self.gap, self.jitter = gap, jitter
        self.backend_factory = backend_factory or cad_programs.Backends
        self.prepared = None                    # import_prepare.Prepared, once start() has succeeded
        self.manifest_path = ""
        self.busy = False                       # touched only on the window's thread
        self._cancel = threading.Event()
        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # -- the worker thread -------------------------------------------------
    def _worker(self):
        with cad_programs.session():           # SolidWorks (COM) is used from this thread only
            try:
                while True:
                    job = self._jobs.get()
                    if job is None:
                        break
                    work, on_done = job
                    result = error = None
                    try:
                        result = work()
                    except BaseException as e:      # shown to the user by the window
                        error = e
                    self.post(lambda r=result, e=error, d=on_done: self._complete(d, r, e))
            finally:
                prepared, self.prepared = self.prepared, None
                if prepared is not None:
                    try:
                        prepared.close()
                    except Exception:
                        pass

    def _complete(self, on_done, result, error):
        self.busy = False
        if on_done:
            on_done(result, error)

    def _submit(self, work, on_done):
        if self.busy:
            raise import_errors.ImportFailed("Still working on the last request.")
        self.busy = True
        self._cancel.clear()
        self._jobs.put((work, on_done))

    def _progress(self, on_progress):
        if on_progress is None:
            return None
        return lambda done, total, text: self.post(lambda: on_progress(done, total, text))

    def _cancel_requested(self):
        return self._cancel.is_set()

    # -- what the window can ask for ---------------------------------------
    def _scan_progress(self, progress):
        def scan_progress(done, total, name):
            if self._cancel_requested():
                raise import_errors.ImportCancelled("Cancelled. Nothing was changed.")
            if progress:
                progress(done, total, f"Scanning: {Path(name).name}")
        return scan_progress

    def scan(self, on_done, on_progress=None, folders=None):
        """Only scan `folders`: on_done(manifest, error), with nothing saved yet. Pass the manifest to
        start(scanned=...) to go on."""
        if not folders:
            raise import_errors.ImportFailed("Choose at least one folder to scan, or open a manifest.")
        scan_progress = self._scan_progress(self._progress(on_progress))
        self._submit(lambda: scan.scan(folders, repo=self.repo, progress=scan_progress), on_done)

    def start(self, on_done, on_progress=None, folders=None, manifest_path=None, manifest_root=None,
              allow_external=False, cots=False, scanned=None):
        """Scan `folders` (writing a manifest), take a scan made by scan() (`scanned`, written the same way) or
        open `manifest_path`, then propose part numbers.

        on_done(proposal, error): the Proposal to show as the table.
        """
        if not folders and not manifest_path and scanned is None:
            raise import_errors.ImportFailed("Choose at least one folder to scan, or open a manifest.")
        progress = self._progress(on_progress)

        def work():
            path = manifest_path
            if folders or scanned is not None:
                found = scanned if scanned is not None else scan.scan(folders, repo=self.repo,
                                                                        progress=self._scan_progress(progress))
                path = str(default_manifest_path(manifest_root)) if manifest_root else str(manifest_path)
                manifest_module.save(found, path)
                self.log(f"Scan saved to {path}")
            self.manifest_path = path
            backend = self.backend_factory()
            try:
                self.prepared = import_prepare.prepare(
                    self.repo, path, backend=backend, allow_external=allow_external, cots=cots,
                    cancel=self._cancel_requested, progress=progress, log=self.log, org=self.org,
                    gap=self.gap, jitter=self.jitter)
            except BaseException:
                close = getattr(backend, "close", None)
                if close:
                    close()
                raise
            self.prepared.owns_backend = True            # the session made it, so closing the session closes it
            return self.prepared.proposal

        self._submit(work, on_done)

    def include(self, item_id, include, on_done):
        def work():
            import_prepare.set_included(self.repo, self.prepared, item_id, include)
            return self.prepared.proposal
        self._submit(work, on_done)

    def set_family(self, base, on_done):
        """Give every automatic row a variant of one base number (or None: separate numbers again).
        on_done(proposal, error); an ImportFailed error means the base can't take that many parts."""
        def work():
            import_numbering.set_family(self.repo, self.prepared.proposal, base)
            return self.prepared.proposal
        self._submit(work, on_done)

    def set_project(self, name, on_done):
        """Import into the project called `name` (None: no project): the automatic rows get numbers from its
        block. on_done(proposal, error); proposal.note says where the numbers now come from."""
        def work():
            try:
                chosen, _projects = create.chosen_project(self.repo, name)
            except (create.CreateError, config.ConfigError, part_number.PNError) as e:
                raise import_errors.ImportFailed(str(e)) from None
            proposal = self.prepared.proposal
            import_numbering.set_project(self.repo, proposal, chosen)
            proposal.note = import_prepare.number_note(self.repo, proposal)
            return proposal
        self._submit(work, on_done)

    def check_duplicates(self, on_done):
        """Look for rows that duplicate parts already in the vault. on_done({row: [warnings]}, error)."""
        def work():
            create_batch.sync_latest(self.repo)
            return import_duplicates.find_duplicates(self.repo, self.prepared)
        self._submit(work, on_done)

    def set_allow_external(self, allowed):
        if self.prepared is not None:
            self.prepared.allow_external = bool(allowed)

    def refresh(self, on_done):
        """Download the newest records and re-check the table. on_done(import_numbering.Refresh, error)."""
        self._submit(lambda: import_numbering.refresh(self.repo, self.prepared.proposal, self.log), on_done)

    def finish(self, on_done, on_progress=None):
        """Finish & Import. on_done(import_plan.Result, error); a PNConflict error carries the rows to highlight."""
        self._submit(lambda: import_finish.finish(self.repo, self.prepared, cancel=self._cancel_requested,
                                             progress=self._progress(on_progress), log=self.log), on_done)

    def cancel(self):
        """Ask the running job to stop. It cleans up after itself and then reports ImportCancelled."""
        self._cancel.set()

    def close(self):
        """End the session (after any running job finishes or is cancelled). Closes SolidWorks if we started it."""
        self._cancel.set()
        self._jobs.put(None)
