"""
job_queue.py - the queue that runs Litterbox's work in the background, one job at a time.

Git can only change one thing in a vault at once, so the jobs run in order on a single worker thread. The window
stays usable: you click, the job joins the queue, and the status banner shows what is running and what is waiting.
This file has no window code, so it can be tested on its own. The window (litterbox_gui.py) gives it a `deliver`
function that hands each finished job back to the window's own thread.

A job goes through four states:

    queued      waiting for its turn
    running     the worker is doing it
    finishing   done; waiting for the window to show the result (the part still counts as busy until it has)
    (gone)      the window called finished(job)

The banner is "ready" when nothing is queued or running, "working" when something is, and "error" while there are
problems nobody has dismissed yet (see ErrorNote). An error stays until it is dismissed, so it is still there when
you come back from a break.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from litterbox.errors import LitterboxError, NothingToSaveError

READY, WORKING, ERROR = "ready", "working", "error"


@dataclass
class Job:
    label: str                       # what the banner says while it runs: "Checking in 3 parts"
    work: object                     # work() -> result, run on the worker thread
    parts: tuple = ()                # the parts (as text) this job changes; they are marked busy until it is done
    kind: str = "task"               # "refresh" jobs are collapsed: only the newest waiting one is kept
    token: object = None             # whatever the window needs to finish the job (its callbacks)
    state: str = "queued"

    def __post_init__(self):
        self.parts = tuple(str(part) for part in self.parts)


@dataclass
class Outcome:
    job: Job
    result: object = None
    error: object = None             # None, a message (a real problem), or a NothingToSaveError


@dataclass
class ErrorNote:
    label: str
    message: str
    advice: str = ""
    when: float = field(default_factory=time.time)


@dataclass
class Banner:
    kind: str                        # READY / WORKING / ERROR
    title: str                       # "Ready" / "Working" / "Error"
    detail: str = ""                 # "Checking in 3 parts - 2 more waiting"
    errors: int = 0                  # how many undismissed problems there are


class JobQueue:
    def __init__(self, deliver):
        self._deliver = deliver
        self._cv = threading.Condition()
        self._waiting = deque()
        self._jobs = []              # every job not yet finished(): queued, running or finishing
        self._running = None
        self._errors = []
        self._thread = None

    # -- adding work -----------------------------------------------------------------------------------------
    def submit(self, job):
        with self._cv:
            if job.kind == "refresh":                    # a newer refresh makes any waiting one pointless
                for old in [j for j in self._waiting if j.kind == "refresh"]:
                    self._waiting.remove(old)
                    self._jobs.remove(old)
                    old.state = "dropped"
            self._waiting.append(job)
            self._jobs.append(job)
            self._start()
            self._cv.notify()
        return job

    def _start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="litterbox-jobs")
            self._thread.start()

    def _loop(self):
        while True:
            with self._cv:
                while not self._waiting:
                    self._cv.wait()
                job = self._waiting.popleft()
                job.state = "running"
                self._running = job
            outcome = self._run(job)
            with self._cv:
                job.state = "finishing"
                self._running = None
                self._cv.notify_all()
            self._deliver(outcome)

    @staticmethod
    def _run(job):
        try:
            return Outcome(job, result=job.work())
        except NothingToSaveError as e:           # not a failure: nothing was different
            return Outcome(job, error=e)
        except LitterboxError as e:
            return Outcome(job, error=str(e))
        except Exception as e:                           # anything unexpected
            return Outcome(job, error=f"Unexpected error: {e!r}")

    def finished(self, job):
        """The window has shown the result: the job's parts are no longer busy."""
        with self._cv:
            if job in self._jobs:
                self._jobs.remove(job)
            self._cv.notify_all()

    # -- what is going on ----------------------------------------------------------------------------------------
    def active(self):
        """True while anything is queued, running or waiting to be shown."""
        with self._cv:
            return bool(self._jobs)

    def working(self):
        """True while anything is queued or running (not just waiting to be shown)."""
        with self._cv:
            return bool(self._waiting) or self._running is not None

    def waiting_count(self):
        with self._cv:
            return len(self._waiting)

    def pending_parts(self):
        """{part as text: the label of the job that is about to change it}. Includes jobs waiting to be shown."""
        with self._cv:
            return {part: job.label for job in self._jobs for part in job.parts}

    def wait_idle(self, timeout=10.0):
        """Block until nothing is left (for tests and for closing). Returns True if it got there in time."""
        end = time.monotonic() + timeout
        with self._cv:
            while self._jobs:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(left)
        return True

    # -- problems --------------------------------------------------------------------------------------------------
    def add_error(self, label, message, advice=""):
        note = ErrorNote(label, message, advice)
        with self._cv:
            self._errors.append(note)
        return note

    def errors(self):
        with self._cv:
            return list(self._errors)

    def dismiss_errors(self):
        with self._cv:
            self._errors.clear()

    # -- the banner ----------------------------------------------------------------------------------------------
    def banner(self):
        with self._cv:
            running, waiting, errors = self._running, len(self._waiting), len(self._errors)
            busy = running is not None or waiting
            if running is not None:
                detail = running.label
            elif waiting:
                detail = self._waiting[0].label
            else:
                detail = ""
            if waiting and running is not None:
                detail += f" - {waiting} more waiting"
            elif waiting > 1:
                detail += f" - {waiting - 1} more waiting"
        if errors:
            problem = "1 problem" if errors == 1 else f"{errors} problems"
            return Banner(ERROR, "Error", f"{problem} - still working: {detail}" if busy else problem, errors)
        if busy:
            return Banner(WORKING, "Working", detail)
        return Banner(READY, "Ready")
