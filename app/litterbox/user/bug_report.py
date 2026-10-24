"""
bug_report.py - Help > Report a problem: a zip of what the Litterbox team needs to see what went wrong, made on
this computer for the person to send (user/report_mail.py) to ADDRESS.

    path = bug_report.make(comment, repo, problems)     # problems: [(what Litterbox was doing, message)]

The zip holds report.txt (the comment, the versions, the problems in the red status bar and the last unexpected
errors with their tracebacks), the log (litterbox.log and litterbox.log.old), settings.yaml and the open vault's
.litterbox/config.yaml. Passwords and tokens in URLs are taken out of every file (redact). Reports are kept in
C:\\Litterbox\\logs\\reports, the newest KEEP of them.
"""

import platform
import re
import zipfile
from datetime import datetime
from pathlib import Path

from litterbox import diagnostics
from litterbox import layout
from litterbox import version
from litterbox.cad import solidworks_versions
from litterbox.errors import LitterboxError
from litterbox.git import runner
from litterbox.user import settings

ADDRESS = "contact+litterbug@halfcatrocketry.com"
REPORTS_DIR = settings.LOG_FILE.parent / "reports"
KEEP = 5                            # older reports are deleted when a new one is made
LOG_BYTES = 2_000_000               # at most this much of each log file goes in (its end)

_URL_SECRET = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)        # https://user:token@host
_TOKENS = re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat|glpat)_[A-Za-z0-9_]{10,}")      # GitHub and GitLab tokens
_HEADER = re.compile(r"(authorization:\s*)\S.*", re.IGNORECASE)


def redact(text):
    """The text with passwords and tokens taken out: from URLs (https://user:token@host -> https://host), the
    common token formats, and Authorization headers."""
    text = _URL_SECRET.sub(r"\1", str(text))
    text = _TOKENS.sub("[token removed]", text)
    return _HEADER.sub(r"\1[removed]", text)


def _tool_version(command):
    try:
        return runner.run(command, str(settings.ROOT if settings.ROOT.is_dir() else Path.cwd()), quiet=True)
    except LitterboxError:
        return "not found"
    except Exception as e:                           # never let a report fail over a version number
        return f"unknown ({e!r})"


def facts():
    """[(name, value)] about this computer, for report.txt and the email."""
    try:
        year = solidworks_versions.installed_year()
    except Exception:
        year = None
    return [("Litterbox", version.display()),
            ("Windows", f"{platform.platform()} ({platform.machine()})"),
            ("Python", platform.python_version()),
            ("SolidWorks", str(year) if year else "not installed"),
            ("Git", _tool_version(["git", "--version"])),
            ("Git LFS", _tool_version(["git", "lfs", "version"]))]


def report_text(comment, repo, problems, computer_facts, when):
    """report.txt: the comment, the facts, the problems in the status bar and the last unexpected errors."""
    lines = [f"Litterbox problem report, {when:%Y-%m-%d %H:%M}", "", "What they were doing:", str(comment).strip(),
             "", "This computer:"]
    lines += [f"  {name}: {value}" for name, value in computer_facts]
    lines += ["", f"Vault: {repo or '(none open)'}", ""]
    lines += ["Problems in the status bar:"] + ([f"  {label}: {message}" for label, message in problems]
                                                 or ["  (none)"])
    lines += ["", "Unexpected errors this session:"]
    errors = diagnostics.unexpected()
    for stamp, where, trace in errors:
        lines += [f"  {stamp}, while {where}:", *("    " + line for line in trace.rstrip().splitlines())]
    if not errors:
        lines.append("  (none)")
    return redact("\n".join(lines) + "\n")


def _tail(path, limit=LOG_BYTES):
    """The end of a text file (at most `limit` bytes), or None if it can't be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def included_files(repo):
    """{name in the zip: file on this computer} for the files that go in besides report.txt."""
    files = {"litterbox.log": settings.LOG_FILE, "litterbox.log.old": Path(str(settings.LOG_FILE) + ".old"),
             "settings.yaml": settings.SETTINGS_FILE}
    if repo:
        files["vault-config.yaml"] = Path(repo) / layout.CONFIG_PATH
    return files


def make(comment, repo, problems=(), folder=None, now=None):
    """Write the report's zip and return its path. `comment` (what they were doing) is required."""
    if not str(comment or "").strip():
        raise LitterboxError("Say briefly what you were doing when the problem happened.")
    when = now or datetime.now()
    folder = Path(folder) if folder else REPORTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"litterbox-report-{when:%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr("report.txt", report_text(comment, repo, list(problems), facts(), when))
        for name, source in included_files(repo).items():
            text = _tail(source)
            if text is not None:
                zipped.writestr(name, redact(text))
    _prune(folder)
    return path


def _prune(folder):
    """Keep only the newest KEEP reports."""
    reports = sorted(Path(folder).glob("litterbox-report-*.zip"))
    for old in reports[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def subject(org):
    return f"Litterbox problem report ({version.VERSION}{', ' + org if org else ''})"


def body(comment, computer_facts):
    """The email's text: the comment and the versions (the rest is in the attached zip)."""
    lines = ["What I was doing:", str(comment).strip(), ""]
    lines += [f"{name}: {value}" for name, value in computer_facts]
    return redact("\n".join(lines))
