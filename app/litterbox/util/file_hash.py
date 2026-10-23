"""
file_hash.py - the SHA-256 of a file's contents, as text (what Git LFS knows a file by, and how the importer and the
sign-offs tell whether two files are the same). The file is read in blocks, so a big CAD file never sits in memory.
"""

import hashlib


def sha256(path):
    """The SHA-256 of the file at `path`, as 64 hex digits. Raises OSError if it can't be read."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
