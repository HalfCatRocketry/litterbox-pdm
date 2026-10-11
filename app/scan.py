"""
scan.py - phase 1 of importing CAD: look at your old folders and write a manifest.

The scan only READS. It never changes, moves, renames or opens-for-writing any
of your files, and it creates nothing in your folders. It writes one file, the
manifest, and refuses to put it inside a folder it is scanning.

    python scan.py <folder> [<folder> ...] [--out import-manifest.yaml] [--repo <vault>] [--no-hash] [--force]

What it does
  * Finds the CAD files (.SLDPRT parts, .SLDASM assemblies, .SLDDRW drawings),
    skipping obvious junk such as ~$ lock files and .bak files.
  * Pairs each drawing with the model that has the same name in the same folder,
    because they will share one part number.
  * Proposes a name for each item from its file name (the old file name goes in
    the description). It never guesses which parts are purchased: everything comes in
    as cots: false, and purchased parts are brought in separately with Import COTS.
  * Hashes every file (SHA-256), so the report can tell you how many are exact copies.
    Copies are NOT merged: each one still gets its own item. They are listed in
    identical_to so you can see them.
  * With --repo, notices files that were already imported from the same path.
  * Adds warnings for things worth a look: backup-looking folders and names,
    very long paths, empty files, unreadable files.

It never opens the files with SolidWorks, so it works with any SolidWorks version
(or with files from any other program that you rename to the same extensions).
Working out what each assembly REFERENCES needs SolidWorks and comes later.
"""

import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import manifest as mf
import registry

# extension (lowercase) -> (kind, display type). Add other CAD programs here.
FORMATS = {
    ".sldprt": ("part", "SLDPRT"),
    ".sldasm": ("assembly", "SLDASM"),
    ".slddrw": ("drawing", "SLDDRW"),
}

IGNORED_FOLDERS = {".git", "$recycle.bin", "system volume information", "swxauto", "__pycache__"}
JUNK_EXTENSIONS = {".bak", ".tmp", ".swp"}
LONG_PATH = 240                 # Windows trips over paths much longer than this
HASH_BLOCK = 1024 * 1024
MAX_NAME_LENGTH = 100

OLD_FOLDER_WORDS = {"old", "backup", "backups", "bak", "archive", "archived", "obsolete", "deprecated",
                    "unused", "trash", "temp", "tmp", "superseded", "discard", "discarded"}
COPY_WORDS = {"old", "bak", "backup", "copy", "obsolete", "deprecated", "unused"}
COPY_NUMBER = re.compile(r"\(\d+\)$")


class ScanError(Exception):
    """The scan could not run. The message is safe to show to a user."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _norm(path):
    return os.path.normcase(os.path.normpath(str(path)))


def _inside(path, folder):
    path, folder = _norm(path), _norm(folder)
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _open_path(path):
    """Windows can't open very long paths unless they start with \\\\?\\ ."""
    if os.name == "nt" and len(path) >= 248 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def hash_file(path):
    digest = hashlib.sha256()
    with open(_open_path(path), "rb") as f:
        while True:
            block = f.read(HASH_BLOCK)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def propose_name(stem):
    """'valve_body' -> 'valve body'. The user can change it in the manifest."""
    name = " ".join(stem.replace("_", " ").split())
    return name or stem


def is_junk(filename):
    lower = filename.lower()
    return lower.startswith("~$") or os.path.splitext(lower)[1] in JUNK_EXTENSIONS


# ---------------------------------------------------------------------------
# Finding the files
# ---------------------------------------------------------------------------

def _walk(sources, skip_folders, stats, errors):
    """Yield (folder, filename) for every file, pruning folders we never want."""
    skip = [_norm(p) for p in skip_folders]

    def on_error(error):
        errors.append(f"Could not read the folder {error.filename}: {error.strerror or error}")

    for source in sources:
        for folder, dirs, files in os.walk(source, onerror=on_error, followlinks=False):
            dirs[:] = sorted(d for d in dirs
                             if d.lower() not in IGNORED_FOLDERS
                             and not any(_inside(os.path.join(folder, d), s) for s in skip))
            for filename in sorted(files):
                yield folder, filename


def _folder_warnings(folder, sources):
    """Warnings that come from where a file lives."""
    relative = folder
    for source in sources:
        if _inside(folder, source):
            relative = os.path.relpath(folder, source)
            break
    parts = [p for p in re.split(r"[\\/]", relative) if p and p != "."]
    warnings = []
    for part in parts:
        if OLD_FOLDER_WORDS & set(_words(part)):
            warnings.append(f"In a folder named '{part}': it may be an old copy or a backup.")
    return warnings


def _name_warnings(stem):
    warnings = []
    if COPY_WORDS & set(_words(stem)) or COPY_NUMBER.search(stem):
        warnings.append("The file name looks like a copy or a backup.")
    return warnings


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

def scan(sources, repo=None, hash_files=True, progress=None):
    """Scan folders and return a Manifest. Reads only. `progress(done, total, path)` is called while hashing."""
    if not sources:
        raise ScanError("Give at least one folder to scan.")
    resolved = []
    for source in sources:
        path = os.path.abspath(str(source))
        if not os.path.isdir(path):
            raise ScanError(f"Not a folder: {source}")
        resolved.append(path)
    skip = [repo] if repo else []

    stats = {"files_seen": 0, "skipped_junk": 0, "other_files": {}}
    errors = []
    groups = defaultdict(lambda: {"models": [], "drawings": []})       # (folder, stem) -> files
    seen_paths = set()                  # folders listed twice, or one inside another, must not count files twice
    for folder, filename in _walk(resolved, skip, stats, errors):
        full = _norm(os.path.join(folder, filename))
        if full in seen_paths:
            continue
        seen_paths.add(full)
        stats["files_seen"] += 1
        if is_junk(filename):
            stats["skipped_junk"] += 1
            continue
        stem, ext = os.path.splitext(filename)
        kind_info = FORMATS.get(ext.lower())
        if not kind_info:
            key = ext.lower() or "(no extension)"
            stats["other_files"][key] = stats["other_files"].get(key, 0) + 1
            continue
        kind, type_name = kind_info
        entry = {"path": os.path.normpath(os.path.join(folder, filename)), "kind": kind, "type": type_name,
                 "stem": stem, "folder": folder}
        key = (_norm(folder), stem.lower())
        groups[key]["drawings" if kind == "drawing" else "models"].append(entry)

    # Pair each drawing with its model; a drawing with no single matching model stands alone.
    raw_items = []
    for key in sorted(groups):
        group = groups[key]
        models, drawings = group["models"], group["drawings"]
        if len(models) == 1:
            raw_items.append((models[0], [models[0]] + drawings, []))
        else:
            for model in models:
                raw_items.append((model, [model], []))
            for drawing in drawings:
                note = ("More than one model has this name, so the drawing was not paired with any of them."
                        if models else "No model with the same name was found beside this drawing; the model it "
                        "shows may be elsewhere (SolidWorks is needed to find out).")
                raw_items.append((drawing, [drawing], [note]))

    # Hash, then build the items.
    all_files = [f for _, files, _ in raw_items for f in files]
    total = len(all_files)
    for done, entry in enumerate(all_files, start=1):
        entry["size"], entry["sha256"], entry["error"] = 0, "", ""
        try:
            entry["size"] = os.path.getsize(_open_path(entry["path"]))
            if hash_files:
                entry["sha256"] = hash_file(entry["path"])
        except OSError as e:
            entry["error"] = str(e.strerror or e)
        if progress:
            progress(done, total, entry["path"])

    items = []
    for number, (main, files, notes) in enumerate(raw_items, start=1):
        warnings = list(notes)
        name = propose_name(main["stem"])
        if len(name) > MAX_NAME_LENGTH:
            warnings.append(f"The name was shortened to {MAX_NAME_LENGTH} characters; the full file name is in the description.")
            name = name[:MAX_NAME_LENGTH].rstrip()
        folder_warnings = _folder_warnings(main["folder"], resolved)
        warnings += folder_warnings + _name_warnings(main["stem"])
        include = True
        for entry in files:
            if entry["error"]:
                warnings.append(f"Could not read {os.path.basename(entry['path'])}: {entry['error']}")
                include = False
            elif entry["size"] == 0:
                warnings.append(f"{os.path.basename(entry['path'])} is empty (0 bytes).")
            if len(entry["path"]) > LONG_PATH:
                warnings.append(f"The path of {os.path.basename(entry['path'])} is very long ({len(entry['path'])} "
                                "characters); Windows may have trouble with it.")
        items.append(mf.Item(
            id=number, name=name, include=include,
            kind="drawing" if main["kind"] == "drawing" else main["kind"],
            description=", ".join(os.path.basename(f["path"]) for f in files),
            files=[mf.FileEntry(f["path"], f["type"], f["size"], f["sha256"]) for f in files],
            warnings=warnings))

    _mark_identical(items)
    if repo:
        _mark_already_imported(items, repo)
    result = mf.Manifest(sources=resolved, items=items, created_at=mf.now_utc())
    result.stats = _stats(items, stats, errors, hash_files)
    return result


def _mark_identical(items):
    """Fill identical_to for items whose main file is byte-for-byte the same. Information only."""
    by_hash = defaultdict(list)
    for item in items:
        if item.files and item.files[0].sha256:
            by_hash[item.files[0].sha256].append(item)
    for same in by_hash.values():
        if len(same) > 1:
            for item in same:
                item.identical_to = [other.id for other in same if other is not item]


def _mark_already_imported(items, repo):
    """Items whose main file was already imported (the vault remembers the old path) are left out by default."""
    known = {}
    for pn in registry.list_pns(repo):
        try:
            record = registry.load(repo, pn)
        except registry.RegistryError:
            continue
        if record.import_path:
            known[_norm(record.import_path)] = str(pn)
    for item in items:
        found = known.get(_norm(item.main_path))
        if found:
            item.already_imported_as = found
            item.include = False
            item.warnings.append(f"This file was already imported as {found}, so it is left out. "
                                 "Set include: true to import it again as a new part.")


def _stats(items, seen, errors, hashed):
    groups = defaultdict(list)
    for item in items:
        if item.files and item.files[0].sha256:
            groups[item.files[0].sha256].append(item)
    copies = [g for g in groups.values() if len(g) > 1]
    wasted = sum(g[0].files[0].size * (len(g) - 1) for g in copies)
    counts = defaultdict(int)
    for item in items:
        counts[item.kind] += 1
    result = {
        "items": len(items),
        "parts": counts["part"],
        "assemblies": counts["assembly"],
        "drawings_without_model": counts["drawing"],
        "files_to_import": sum(len(i.files) for i in items),
        "total_bytes": sum(f.size for i in items for f in i.files),
        "hashed": bool(hashed),
        "groups_of_identical_files": len(copies),
        "extra_identical_copies": sum(len(g) - 1 for g in copies),
        "bytes_in_extra_copies": wasted,
        "items_with_warnings": sum(1 for i in items if i.warnings),
        "already_imported": sum(1 for i in items if i.already_imported_as),
        "files_seen": seen["files_seen"],
        "skipped_junk_files": seen["skipped_junk"],
        "other_files": dict(sorted(seen["other_files"].items(), key=lambda kv: -kv[1])[:15]),
    }
    if errors:
        result["unreadable_folders"] = errors
    return result


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _size(n):
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024


def format_report(manifest):
    s = manifest.stats
    lines = [
        f"Scanned {len(manifest.sources)} folder(s), looked at {s['files_seen']:,} files.",
        f"Found {s['items']:,} items to import: {s['parts']:,} parts, {s['assemblies']:,} assemblies"
        + (f", {s['drawings_without_model']:,} drawings whose model wasn't found" if s["drawings_without_model"] else "")
        + f".  ({s['files_to_import']:,} files, {_size(s['total_bytes'])})",
    ]
    if s["hashed"]:
        if s["groups_of_identical_files"]:
            lines.append(f"Exact copies: {s['extra_identical_copies']:,} items are byte-for-byte copies of another item "
                         f"({s['groups_of_identical_files']:,} groups, {_size(s['bytes_in_extra_copies'])} in the extra copies). "
                         "They are NOT merged; each still gets its own part number.")
        else:
            lines.append("No exact copies were found.")
    if s["already_imported"]:
        lines.append(f"Left out because they were already imported: {s['already_imported']:,}.")
    if s["items_with_warnings"]:
        lines.append(f"Items with warnings: {s['items_with_warnings']:,} (see warnings: in the manifest).")
    if s["skipped_junk_files"]:
        lines.append(f"Skipped {s['skipped_junk_files']:,} junk files (~$ lock files, .bak, .tmp).")
    if s.get("unreadable_folders"):
        lines.append(f"{len(s['unreadable_folders'])} folder(s) could not be read:")
        lines += [f"  {message}" for message in s["unreadable_folders"][:10]]
    if s["other_files"]:
        top = ", ".join(f"{ext} x{count:,}" for ext, count in list(s["other_files"].items())[:8])
        lines.append(f"Other files ignored: {top}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Litterbox: scan old CAD folders and write an import manifest (read-only)")
    parser.add_argument("folders", nargs="+", help="the folders to scan")
    parser.add_argument("--out", default="import-manifest.yaml", help="where to write the manifest")
    parser.add_argument("--repo", help="your vault folder: files already imported from the same path are left out")
    parser.add_argument("--no-hash", action="store_true", help="skip hashing (much faster, but no exact-copy report)")
    parser.add_argument("--force", action="store_true", help="overwrite the manifest file if it already exists")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    try:
        for folder in args.folders:
            if _inside(out, os.path.abspath(folder)):
                raise ScanError(f"The manifest can't be written inside a folder being scanned ({folder}). "
                                "Choose another place with --out.")
        if out.exists() and not args.force:
            raise ScanError(f"{out} already exists. It may hold edits you made. Use --force to replace it, "
                            "or choose another name with --out.")

        def show(done, total, path):
            if done == total or done % 50 == 0:
                print(f"\r  hashed {done:,} of {total:,} files", end="", flush=True)

        result = scan(args.folders, repo=args.repo, hash_files=not args.no_hash, progress=show)
        print()
        mf.save(result, out)
    except (ScanError, mf.ManifestError) as e:
        print(f"\nERROR: {e}")
        return 1
    print(format_report(result))
    print(f"\nManifest written to {out}\nNothing in your CAD folders was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())