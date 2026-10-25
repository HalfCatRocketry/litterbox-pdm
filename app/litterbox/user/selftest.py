"""
selftest.py - a quick check, run by the release pipeline on the freshly built program (and by you, if you like):

    Litterbox.exe --self-test result.txt

It opens no window. It checks that every part of the program, and every library and data file it needs, made it
into the build, and writes "ok" or the problems to the file (or the screen). The exit code is 0 only if all is well.
A build that fails this is never published.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

MIN_MODULES = 150           # the program has about 185 modules; finding far fewer means the build lost some
LIBRARIES = ("yaml", "customtkinter", "tkinter", "cryptography")
WINDOWS_LIBRARIES = ("win32com.client", "pythoncom", "pywintypes", "win32timezone")


def app_modules():
    """Every module of the litterbox package (found by walking it, so a new module is checked without a list to
    keep up to date). Works from source and in the PyInstaller build."""
    import litterbox
    return sorted(info.name for info in pkgutil.walk_packages(litterbox.__path__, "litterbox.")
                  if not info.name.endswith("__main__"))           # __main__ runs the command line when imported


def problems(assets_dir=None):
    """A list of what is wrong; empty if all is well."""
    found = []
    modules = app_modules()
    if len(modules) < MIN_MODULES:
        found.append(f"only {len(modules)} litterbox modules were found (expected at least {MIN_MODULES})")
    for name in modules + list(LIBRARIES) + list(WINDOWS_LIBRARIES if sys.platform == "win32" else ()):
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
        from litterbox.gui.logic import icon_files
        if assets_dir is not None and icon_files.find_icon(assets_dir) is None:
            found.append(f"the icon files are missing from {assets_dir}")
    except Exception as e:
        found.append(f"icon check failed: {e!r}")
    try:
        from litterbox.user import updater
        private, public = updater.generate_keypair()
        if not updater.signature_is_good(b"x", updater.sign(b"x", private), public):
            found.append("signature check does not work")
        for spare in updater.SPARE_PUBLIC_KEYS:
            if not updater.is_public_key(spare):
                found.append(f"the spare update key {spare!r} is not a valid public key")
        for revoked in updater.REVOKED_PUBLIC_KEYS:
            if not updater.is_public_key(revoked):
                found.append(f"the revoked update key {revoked!r} is not a valid public key")
            if revoked in updater.SPARE_PUBLIC_KEYS:
                found.append(f"the spare update key {revoked!r} is also revoked")
    except Exception as e:
        found.append(f"signature check failed: {e!r}")
    try:
        from litterbox import version
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
