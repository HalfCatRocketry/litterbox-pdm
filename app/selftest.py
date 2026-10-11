"""
selftest.py - a quick check, run by the release pipeline on the freshly built program (and by you, if you like):

    Litterbox.exe --self-test result.txt

It opens no window. It checks that every part of the program, and every library and data file it needs, made it
into the build, and writes "ok" or the problems to the file (or the screen). The exit code is 0 only if all is well.
A build that fails this is never published.
"""

import importlib
import sys
from pathlib import Path

APP_MODULES = ("config", "create", "gui_logic", "import_session", "importer", "litterbox_engine", "manifest",
               "opener", "people", "pn", "references", "registry", "revise", "scan", "settings", "signing",
               "sw_probe", "updater", "version", "build_info")
LIBRARIES = ("yaml", "customtkinter", "tkinter", "cryptography")
WINDOWS_LIBRARIES = ("win32com.client", "pythoncom", "pywintypes", "win32timezone")


def problems(assets_dir=None):
    """A list of what is wrong; empty if all is well."""
    found = []
    for name in APP_MODULES + LIBRARIES + (WINDOWS_LIBRARIES if sys.platform == "win32" else ()):
        try:
            importlib.import_module(name)
        except Exception as e:
            found.append(f"cannot import {name}: {e!r}")
    try:
        import customtkinter
        theme = Path(customtkinter.__file__).parent / "assets" / "themes" / "blue.json"
        if not theme.is_file():
            found.append(f"CustomTkinter's theme files are missing ({theme})")
    except Exception as e:
        found.append(f"customtkinter check failed: {e!r}")
    try:
        import gui_logic
        if assets_dir is not None and gui_logic.find_icon(assets_dir) is None:
            found.append(f"the icon files are missing from {assets_dir}")
    except Exception as e:
        found.append(f"icon check failed: {e!r}")
    try:
        import updater
        private, public = updater.generate_keypair()
        if not updater.signature_is_good(b"x", updater.sign(b"x", private), public):
            found.append("signature check does not work")
    except Exception as e:
        found.append(f"signature check failed: {e!r}")
    try:
        import version
        version.parse(version.VERSION)
    except Exception as e:
        found.append(f"version is not valid: {e!r}")
    return found


def run(result_path=None, assets_dir=None):
    found = problems(assets_dir)
    text = "ok" if not found else "PROBLEMS:\n" + "\n".join(found)
    if result_path:
        Path(result_path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if not found else 1
