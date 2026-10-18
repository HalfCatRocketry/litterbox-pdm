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
PACKAGE = APP / "litterbox"

# Files that are not Python code but must travel with the program:
#   assets         the Litterbox icons (litterbox/gui/assets; the program looks for them in "assets" when built)
#   customtkinter  its colour themes and fonts (it looks for them next to its own code)
datas = [(str(PACKAGE / "gui" / "assets"), "assets")] + collect_data_files("customtkinter")

# Every module of the litterbox package, read from the files on disk. Some are only imported inside functions,
# which PyInstaller can't always see, so the whole package is listed and none can be left out by accident.
package_modules = sorted(
    ".".join(path.relative_to(APP).with_suffix("").parts).removesuffix(".__init__")
    for path in PACKAGE.rglob("*.py") if "__pycache__" not in path.parts
)
hiddenimports = package_modules + ["win32com", "win32com.client", "pythoncom", "pywintypes", "win32timezone"]

a = Analysis(
    [str(APP / "main.py")],
    pathex=[str(APP)],
    hookspath=[str(ROOT / "packaging" / "hooks")],      # our own PyInstaller hooks, if any are needed
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
    icon=str(PACKAGE / "gui" / "assets" / "litterbox_icon_white.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Litterbox")
