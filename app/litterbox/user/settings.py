"""
settings.py - your personal Litterbox settings and log file.

These live OUTSIDE the vault, on your own computer, and are never shared:

    C:\\Litterbox\\settings.yaml        which vault the app opens, and options such as
                                       debug_mode: true      more detail in the log
                                       update_check: false   don't look for a newer Litterbox
                                       download: all         download every CAD file, not just those you use
    C:\\Litterbox\\logs\\litterbox.log   every git command and error, for troubleshooting

Nothing in here is ever allowed to crash the app: if a file can't be read or
written, we quietly carry on with the defaults.
"""

from datetime import datetime
from pathlib import Path

import yaml

from litterbox.util import fast_yaml

ROOT = Path("C:/Litterbox")
SETTINGS_FILE = ROOT / "settings.yaml"
LOG_FILE = ROOT / "logs" / "litterbox.log"
MAX_LOG_BYTES = 2_000_000          # when the log gets bigger than this it is moved to litterbox.log.old

DEFAULTS = {"repo": r"C:\Litterbox\hcr-litterbox", "debug_mode": False, "update_check": True}

# True when settings.yaml says "debug_mode: true". The app copies it here at start-up. Extra detail for
# troubleshooting (button clicks, slow commands, freezes, a seconds counter) is shown and logged only then.
DEBUG = False


def update_check_enabled(data):
    """Should the installed program look for a newer version when it starts? Yes unless update_check is false."""
    value = data.get("update_check", True) if isinstance(data, dict) else True
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "off", "0")
    return value is not False and value != 0


def downloads_on_demand(data):
    """Download CAD files only when they are used (download: on_demand, the default), or everything (download: all).
    See parts/downloads.py."""
    value = data.get("download", "on_demand") if isinstance(data, dict) else "on_demand"
    return not (isinstance(value, str) and value.strip().lower() in ("all", "everything"))


def _switch(data, name, default):
    value = data.get(name, default) if isinstance(data, dict) else default
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return value is True or (value == 1 and not isinstance(value, bool))


def solidworks_watch(data):
    """Watch what SolidWorks has open (solidworks_watch: true; off by default). See cad/solidworks/sw_watcher.py."""
    return _switch(data, "solidworks_watch", False)


def solidworks_popups(data):
    """With the SolidWorks watcher on, ask and warn in pop-ups (the default), or only in the log
    (solidworks_popups: false)."""
    return _switch(data, "solidworks_popups", True)


def is_debug(data):
    """Read debug_mode from loaded settings. Only a real true / "true" / "yes" / "on" turns it on."""
    value = data.get("debug_mode", False) if isinstance(data, dict) else False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return value is True


def load(path=None):
    """Read the settings file. Anything missing or unreadable falls back to DEFAULTS."""
    path = Path(path) if path else SETTINGS_FILE
    data = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as f:
            loaded = fast_yaml.safe_load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except (OSError, yaml.YAMLError):
        pass
    return data


def save(data, path=None):
    """Write the settings file. Returns True if it worked."""
    path = Path(path) if path else SETTINGS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        return True
    except (OSError, yaml.YAMLError):
        return False


def append_log(text, path=None):
    """Add one timestamped line to the log file."""
    path = Path(path) if path else LOG_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_name(path.name + ".old"))
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            for line in str(text).splitlines() or [""]:
                f.write(f"{stamp}  {line}\n")
    except OSError:
        pass