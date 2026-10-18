"""
import_duplicates.py - spotting files the vault already has (the same contents), so they are not
imported twice.
"""

import os
from pathlib import Path

from litterbox.git import lfs_download
from litterbox.importing import import_paths
from litterbox.records import record_files
from litterbox.records import record_model
from litterbox.records import record_store


def _sha256(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicates(repo, prepared):
    """{row index: [warning, ...]} for rows that look like a part Litterbox already has.

    A row is a likely duplicate when
      * a file in the vault's cad folder has exactly the same contents as the row's main file, or
      * a part with exactly the same Name is already in the vault, or
      * another row of this same import has the same file contents or the same Name.
    Only a warning: the caller decides what to do. Reads the local copy of the vault; sync first for the newest.
    Vault files are only read when their size matches, so this stays quick on a big vault.
    """
    entries = prepared.proposal.entries
    org = prepared.proposal.org
    found = {}

    def warn(index, text):
        found.setdefault(index, []).append(text)

    # names already in the vault
    by_name = {}
    for pn in record_store.list_pns(repo, org):
        try:
            by_name.setdefault(record_store.load(repo, pn).name, []).append(pn)
        except record_model.RegistryError:
            continue

    # same contents: only look at vault files whose size and type match
    wanted = {}
    for index, entry in enumerate(entries):
        main_file = entry.item.files[0]
        try:
            size = os.path.getsize(main_file.path)
        except OSError:
            continue
        wanted.setdefault((size, import_paths.ext_of(main_file.path)), []).append(index)
    hashes = {}
    for pn, revisions in record_files.cad_index(repo).items():
        for rel in sorted(f for files in revisions.values() for f in files):
            path = Path(repo) / rel
            pointer = lfs_download.pointer_info(path)          # not downloaded: the pointer knows size and hash
            try:
                key = (pointer[1] if pointer else path.stat().st_size, import_paths.ext_of(rel))
            except OSError:
                continue
            if key not in wanted:
                continue
            try:
                hashes.setdefault(pointer[0] if pointer else _sha256(path), []).append(pn)
            except OSError:
                continue
    digests = {}
    for index, entry in enumerate(entries):
        main_file = entry.item.files[0]
        if (os.path.getsize(main_file.path) if os.path.isfile(main_file.path) else -1, import_paths.ext_of(main_file.path)) not in wanted:
            continue
        digest = main_file.sha256 or _sha256(main_file.path)
        digests[index] = digest
        for pn in hashes.get(digest, []):
            warn(index, f"The file is identical to the one in the vault for {pn}.")

    for index, entry in enumerate(entries):
        for pn in by_name.get(entry.name, []):
            warn(index, f"A part with exactly this name already exists: {pn}.")
    names, same_file = {}, {}
    for index, entry in enumerate(entries):
        names.setdefault(entry.name, []).append(index)
        if index in digests:
            same_file.setdefault(digests[index], []).append(index)
    for group, what in (*((rows, "name") for rows in names.values()), *((rows, "file") for rows in same_file.values())):
        if len(group) > 1:
            for index in group:
                others = ", ".join(str(i + 1) for i in group if i != index)
                warn(index, f"Row {others} in this import has the same {what}.")
    return found
