# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the Litterbox program. Run from the repository's top folder:
#
#     pyinstaller packaging/litterbox.spec --noconfirm --distpath dist --workpath build
#
# It makes dist/Litterbox/ (Litterbox.exe plus everything it needs). The installer script packs that folder up.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
APP = ROOT / "app"

# Files that are not Python code but must travel with the program:
#   assets/        the Litterbox icons
#   customtkinter  its colour themes and fonts (it looks for them next to its own code)
datas = [(str(APP / "assets"), "assets")] + collect_data_files("customtkinter")

# Modules that are only imported inside functions, or by name, so the build is told about them outright.
hiddenimports = [
    "selftest", "updater", "build_info", "sw_probe", "signing", "people", "references",
    "win32com", "win32com.client", "pythoncom", "pywintypes", "win32timezone",
]

a = Analysis(
    [str(APP / "litterbox_gui.py")],
    pathex=[str(APP)],
    hookspath=[str(ROOT / "packaging" / "hooks")],      # see hooks/hook-workflow.py
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Litterbox",
    console=False,                                   # a window program: no black console behind it
    icon=str(APP / "assets" / "litterbox_icon_white.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Litterbox")
