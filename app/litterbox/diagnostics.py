"""
diagnostics.py - where Litterbox's log messages go, and debug-mode timing.

    LOG     a function that takes one line of text. print by default; the window replaces it so the lines show
            up in its log box. Always call it as diagnostics.LOG(...) so the replacement is seen everywhere.
    DEBUG   set from settings.yaml (debug_mode). When on, slow commands are logged and batches report where
            their time went.
"""

import threading
import time
from functools import wraps

LOG = print
DEBUG = False
SLOW_SECONDS = 2.0          # in debug mode, commands slower than this are logged


# Debug mode: how long each kind of command took, so a slow batch can be explained (see timed).
_TIMES = {}
_TIMES_LOCK = threading.Lock()


def note_time(command, elapsed):
    key = " ".join(command[:3] if command[:2] == ["git", "lfs"] else command[:2])
    with _TIMES_LOCK:
        total, count = _TIMES.get(key, (0.0, 0))
        _TIMES[key] = (total + elapsed, count + 1)


def timed(label):
    """Decorator for the batch functions: in debug mode, log how long the batch took and where the time went, e.g.
    'Timing: check in on 20 part(s) took 31.2s. git commit x20 = 19.8s; git push x1 = 6.1s; ...'. Commands that
    run side by side (locks) add up to more than the total."""
    def decorate(func):
        @wraps(func)
        def wrapper(repo, things, *args, **kwargs):
            if not DEBUG:
                return func(repo, things, *args, **kwargs)
            with _TIMES_LOCK:
                before = dict(_TIMES)
            started = time.monotonic()
            try:
                return func(repo, things, *args, **kwargs)
            finally:
                total = time.monotonic() - started
                with _TIMES_LOCK:
                    after = dict(_TIMES)
                spent = sorted(((after[key][0] - before.get(key, (0.0, 0))[0],
                                 after[key][1] - before.get(key, (0.0, 0))[1], key) for key in after), reverse=True)
                parts = "; ".join(f"{key} x{count} = {seconds:.1f}s" for seconds, count, key in spent if count)
                LOG(f"Timing: {label} on {len(things) if hasattr(things, '__len__') else 1} part(s) took "
                    f"{total:.1f}s. {parts}")
        return wrapper
    return decorate
