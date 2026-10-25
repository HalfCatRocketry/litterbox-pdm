"""
third_party_licenses.py - the licences of everything the built program carries, written beside Litterbox.exe in a
licenses folder (litterbox.spec calls it after the build). Their licences ask that a copy goes with the program.

    third_party_licenses.write(out_folder, repo_root)           # raises SystemExit if a licence can't be found

What goes in:
  * Litterbox's own LICENSE;
  * Python's LICENSE.txt, which also covers what the Windows build of Python brings (Tcl/Tk, OpenSSL, zlib, ...);
  * every package in requirements.txt's "To run" section and the packages they need, from their own dist-info;
  * PyInstaller's licence (its bootloader is inside Litterbox.exe; its other parts only build it);
  * the Roboto fonts customtkinter brings (Apache 2.0, which customtkinter doesn't carry a copy of).
README.txt in the folder lists them all.
"""

import importlib.metadata
import re
import shutil
import sys
from pathlib import Path

from packaging.requirements import Requirement

# Only their own licence (their dependencies don't go in the program), and what part of them is in it.
BUILD_TOOLS = {"pyinstaller": "GPL-2.0 with its Bootloader Exception: only the bootloader, which starts Litterbox.exe"}
_LICENCE_NAME = re.compile(r"(?i)^(licen[cs]e|copying|notice)")
_RUN_SECTION = re.compile(r"^# --- To run ---$(.*?)(?=^# ---|\Z)", re.M | re.S)


def runtime_requirements(requirements_text):
    """The names in requirements.txt's "To run" section that apply on this computer."""
    section = _RUN_SECTION.search(requirements_text)
    if not section:
        raise SystemExit("requirements.txt has no '# --- To run ---' section.")
    names = []
    for line in section.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate():
                names.append(requirement.name)
    return names


def _key(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def with_dependencies(names):
    """[Distribution] for these packages and everything they need, each once, in the order found."""
    found = {}

    def walk(name):
        if _key(name) in found:
            return
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            raise SystemExit(f"{name} is not installed, so its licence can't go in the build.") from None
        found[_key(name)] = dist
        for line in dist.requires or ():
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                walk(requirement.name)

    for name in names:
        walk(name)
    return list(found.values())


def licence_files(dist):
    """{name in its folder: file on disk}: the dist-info's licenses/ folder (PEP 639) if it has one, else the
    licence files in the dist-info, else any licence file the package installed."""
    files = [f for f in dist.files or () if _LICENCE_NAME.match(f.name)]
    in_folder = [f for f in files if ".dist-info/licenses/" in f.as_posix()]
    in_dist_info = [f for f in files if f.parent.name.endswith(".dist-info")]
    chosen = in_folder or in_dist_info or files
    out = {}
    for f in chosen:
        if in_folder:
            name = f.as_posix().split(".dist-info/licenses/", 1)[-1]
        else:
            name = f.name if in_dist_info else f.as_posix().replace("/", "_")
        out[name] = Path(dist.locate_file(f))
    return out


def _licence_of(dist):
    meta = dist.metadata
    text = meta.get("License-Expression") or meta.get("License") or ""
    if not text or len(text) > 60:
        classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or () if c.startswith("License ::")]
        text = ", ".join(classifiers) or "see its files"
    return text.strip()


def write(out, root, build_tools=BUILD_TOOLS):
    """Fill `out` (made afresh) with the licences, and README.txt listing them. `root` is the repository."""
    out, root = Path(out), Path(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rows = []

    def put(folder, files, what, licence):
        if not files:
            raise SystemExit(f"No licence file was found for {what}.")
        for name, source in files.items():
            target = out / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        rows.append((what, licence, folder))

    put("Litterbox", {"LICENSE.txt": root / "LICENSE"}, "Litterbox", "MIT")
    python = f"Python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    put(python, {"LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt"},
        f"Python {python.split('-')[1]}", "PSF-2.0, with Tcl/Tk, OpenSSL, zlib and the rest its build includes")
    names = runtime_requirements((root / "requirements.txt").read_text(encoding="utf-8"))
    dists = with_dependencies(names) + [importlib.metadata.distribution(name) for name in build_tools]
    apache = None
    for dist in dists:
        files = licence_files(dist)
        apache = apache or next((p for n, p in files.items() if n.endswith("LICENSE.APACHE")), None)
        put(f"{dist.metadata['Name']}-{dist.version}", files, f"{dist.metadata['Name']} {dist.version}",
            build_tools.get(_key(dist.metadata["Name"])) or _licence_of(dist))
    if any(_key(d.metadata["Name"]) == "customtkinter" for d in dists):
        if apache is None:
            raise SystemExit("No copy of the Apache 2.0 licence was found for the Roboto fonts.")
        put("Roboto-font", {"LICENSE.txt": apache}, "Roboto font (Google), brought by customtkinter", "Apache-2.0")
    lines = ["Litterbox is free software under the MIT licence (Litterbox/LICENSE.txt).",
             "It is built with, and carries, these other people's programs. Each folder here holds its licence.", ""]
    width = max(len(what) for what, _, _ in rows)
    lines += [f"{what.ljust(width)}  {licence}  ->  {folder}" for what, licence, folder in rows]
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows
