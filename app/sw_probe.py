"""
sw_probe.py - a READ-ONLY look at how SolidWorks sees one assembly.

This is an experiment, not part of Litterbox itself. It answers: can Litterbox
talk to your SolidWorks from Python, and what does SolidWorks say an assembly
is made of? That is what the real importer will need to rename files safely.

    python sw_probe.py "C:\\path\\to\\Some Assembly.SLDASM"  [--report sw-probe-report.txt]

What it does
  1. Records every file in the assembly's folder (size, time, SHA-256 for CAD files).
  2. Connects to SolidWorks (starting it if it isn't running) and prints its version.
  3. Checks which of the API calls the importer will want exist in your SolidWorks.
  4. Opens the assembly READ-ONLY, lists every component and where SolidWorks
     found it, then closes the assembly WITHOUT saving.
  5. Records the folder again and tells you whether anything changed.

It never saves, never renames, never writes. Opening a file in SolidWorks can
sometimes create a temporary ~$ lock file; step 5 checks that none is left behind.
If SolidWorks asks you anything (for example to upgrade an old file), answer so
that NOTHING is saved. Files from older SolidWorks versions are only upgraded in
memory, never on disk, unless you save them.

Send the report file (sw-probe-report.txt) back; it has no private information
other than file names and folder paths.
"""

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

# Values of SolidWorks' swDocumentTypes_e and swOpenDocOptions_e, as I understand them.
# Please treat them as unverified until this has run once on a real installation.
DOC_ASSEMBLY = 2
OPEN_SILENT = 1
OPEN_READ_ONLY = 2

# API members the importer is likely to need. The probe only checks that they exist.
CAPABILITIES = [
    ("RevisionNumber", "reads the SolidWorks version"),
    ("OpenDoc6", "opens a file"),
    ("CloseDoc", "closes a file without saving"),
    ("GetDocumentDependencies2", "lists what a file references without opening it"),
    ("ReplaceReferencedDocument", "points a file at a different file (updates a reference)"),
    ("CopyDocument", "copies a file, updating references"),
    ("MoveDocument", "moves or renames a file, updating references"),
    ("GetOpenDocumentByName", "finds a file that is already open"),
]

CAD_EXTENSIONS = {".sldprt", ".sldasm", ".slddrw"}


# ---------------------------------------------------------------------------
# Folder snapshots (to prove nothing changed)
# ---------------------------------------------------------------------------

def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot(folder):
    """{relative path: (size, modified time, sha256 or '')} for everything under `folder`."""
    result = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            path = os.path.join(root, name)
            try:
                stat = os.stat(path)
                digest = _sha256(path) if os.path.splitext(name)[1].lower() in CAD_EXTENSIONS else ""
            except OSError as e:
                result[os.path.relpath(path, folder)] = (-1, 0, f"unreadable: {e}")
                continue
            result[os.path.relpath(path, folder)] = (stat.st_size, stat.st_mtime_ns, digest)
    return result


def compare(before, after):
    """What changed between two snapshots: (added, removed, modified) lists of relative paths."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    return added, removed, modified


# ---------------------------------------------------------------------------
# Talking to SolidWorks
# ---------------------------------------------------------------------------

def call(obj, name, *args):
    """Read a SolidWorks property or call a method, whichever `name` turns out to be.

    Through Python's COM bridge some SolidWorks members behave like properties
    and some like methods, and it is not always obvious which; this handles both.
    """
    attribute = getattr(obj, name)
    return attribute(*args) if callable(attribute) else attribute


def has_member(obj, name):
    try:
        getattr(obj, name)
        return True
    except Exception:
        return False


def connect():
    """Attach to a running SolidWorks, or start one. Returns (sw, started_by_us)."""
    import win32com.client
    try:
        return win32com.client.GetActiveObject("SldWorks.Application"), False
    except Exception:
        return win32com.client.Dispatch("SldWorks.Application"), True


def open_read_only(sw, path):
    """Open an assembly read-only. Returns (model or None, error code, warning code)."""
    import pythoncom
    from win32com.client import VARIANT
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = sw.OpenDoc6(path, DOC_ASSEMBLY, OPEN_READ_ONLY | OPEN_SILENT, "", errors, warnings)
    return model, errors.value, warnings.value


def describe_components(model, wrap=lambda x: x):
    """One dict per component in the assembly (all levels), as SolidWorks reports them."""
    components = call(model, "GetComponents", False) or []
    found = []
    for raw in components:
        comp = wrap(raw)
        entry = {}
        for key, member in (("name", "Name2"), ("path", "GetPathName"), ("suppressed", "IsSuppressed"),
                            ("configuration", "ReferencedConfiguration")):
            try:
                entry[key] = call(comp, member)
            except Exception as e:                       # report it; never stop the probe for one field
                entry[key] = f"(could not read: {e})"
        found.append(entry)
    return found


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def probe(assembly, sw, started_by_us=False, wrap=lambda x: x, open_func=None, log=print):
    """Run the whole read-only look. Returns the list of report lines (also sent to `log`)."""
    lines = []

    def say(text=""):
        lines.append(text)
        log(text)

    assembly = os.path.abspath(assembly)
    folder = os.path.dirname(assembly)
    say(f"Assembly: {assembly}")
    before = snapshot(folder)
    say(f"Recorded {len(before)} files in {folder}")

    try:
        sw.Visible = True
    except Exception:
        pass
    try:
        version = call(sw, "RevisionNumber")
        major = int(str(version).split(".")[0])
        say(f"SolidWorks version: {version}  (that is SolidWorks {1992 + major})"
            + ("   [started by this script]" if started_by_us else "   [was already running]"))
    except Exception as e:
        say(f"Could not read the SolidWorks version: {e}")

    say()
    say("API members the importer would use:")
    for name, purpose in CAPABILITIES:
        say(f"  {'yes' if has_member(sw, name) else 'NO '}  {name:<28} {purpose}")

    say()
    say("What SolidWorks says the file depends on (without opening it):")
    try:
        deps = call(sw, "GetDocumentDependencies2", assembly, True, False, False)
        deps = list(deps) if deps else []
        say(f"  {len(deps)} entries returned" + (":" if deps else "."))
        for entry in deps[:40]:
            say(f"    {entry}")
        if len(deps) > 40:
            say(f"    ... and {len(deps) - 40} more")
    except Exception as e:
        say(f"  not available: {e}")

    say()
    model = None
    try:
        opener = open_func or open_read_only
        model, error_code, warning_code = opener(sw, assembly)
        say(f"Opened read-only: {'yes' if model else 'NO'}  (error code {error_code}, warning code {warning_code})")
        if model:
            components = describe_components(model, wrap)
            say(f"Components (all levels): {len(components)}")
            outside = 0
            for entry in components:
                path = entry["path"]
                inside = isinstance(path, str) and path.lower().startswith(folder.lower())
                exists = isinstance(path, str) and os.path.exists(path)
                outside += 0 if inside else 1
                say(f"  {entry['name']}")
                say(f"      path: {path}")
                say(f"      {'in the same folder' if inside else 'OUTSIDE the assembly folder'}; "
                    f"{'file exists' if exists else 'FILE NOT FOUND'}; "
                    f"suppressed={entry['suppressed']}; configuration={entry['configuration']}")
            say(f"{outside} component(s) live outside the assembly's folder.")
    except Exception as e:
        say(f"Opening the assembly failed: {e!r}")
    finally:
        if model is not None:
            try:
                title = call(model, "GetTitle")
                sw.CloseDoc(title)                      # CloseDoc never saves
                say(f"Closed '{title}' without saving.")
            except Exception as e:
                say(f"Could not close the assembly ({e!r}). Close it yourself in SolidWorks WITHOUT saving.")

    time.sleep(1)                                       # let SolidWorks remove its temporary lock file
    after = snapshot(folder)
    added, removed, modified = compare(before, after)
    say()
    if not (added or removed or modified):
        say(f"CHECK PASSED: none of the {len(before)} files in the folder changed, and none were added or removed.")
    else:
        say("CHECK FAILED: the folder is different from before.")
        for label, names in (("added", added), ("removed", removed), ("modified", modified)):
            for name in names:
                say(f"  {label}: {name}")
    return lines


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: read-only look at an assembly through SolidWorks")
    parser.add_argument("assembly", help="the .SLDASM file to look at")
    parser.add_argument("--report", default="sw-probe-report.txt", help="where to save the report")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.assembly) or not args.assembly.lower().endswith(".sldasm"):
        print(f"ERROR: {args.assembly} is not an existing .SLDASM file.")
        return 1
    try:
        import win32com.client                            # noqa: F401
    except ImportError:
        print("ERROR: pywin32 is not installed. Run:  pip install pywin32")
        return 1
    try:
        sw, started = connect()
    except Exception as e:
        print(f"ERROR: could not connect to SolidWorks: {e}")
        return 1

    import win32com.client
    lines = probe(args.assembly, sw, started, wrap=win32com.client.Dispatch)
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nReport saved to {Path(args.report).resolve()}")
    print("SolidWorks was left open. Close it when you like (do not save anything).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
