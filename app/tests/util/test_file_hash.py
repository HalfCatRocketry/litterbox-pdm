"""util/file_hash.py: the same digest as hashlib's, for an empty file and one bigger than a read block."""

import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from litterbox.util import file_hash


class Sha256(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_matches_hashlib(self):
        for size in (0, 1, 3 * 1024 * 1024 + 7):
            data = os.urandom(size)
            path = self.folder / f"f{size}"
            path.write_bytes(data)
            self.assertEqual(file_hash.sha256(path), hashlib.sha256(data).hexdigest())

    def test_a_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            file_hash.sha256(self.folder / "missing")


if __name__ == "__main__":
    unittest.main()
