"""git/read_only.py: deleting files that may be read-only, and making a file read-only without touching one that is."""

import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from litterbox.git import read_only
from tests.support import temp_folders


class DeleteFiles(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.repo)
        (self.repo / "cad").mkdir()

    def test_a_read_only_file_is_deleted(self):
        file = self.repo / "cad" / "HCR-00001-001_A.SLDPRT"
        file.write_bytes(b"x")
        os.chmod(file, stat.S_IREAD)
        read_only.delete_file(file)
        self.assertFalse(file.exists())

    def test_a_missing_file_is_fine(self):
        read_only.delete_file(self.repo / "cad" / "nothing.SLDPRT")

    def test_delete_files_says_which_ones_could_not_be_deleted(self):
        (self.repo / "cad" / "a.txt").write_bytes(b"x")
        (self.repo / "cad" / "folder.txt").mkdir()              # a folder can't be deleted as a file
        problems = read_only.delete_files(self.repo, ["cad/a.txt", "cad/folder.txt", "cad/missing.txt"])
        self.assertFalse((self.repo / "cad" / "a.txt").exists())
        self.assertEqual([line.split(":")[0] for line in problems], ["cad/folder.txt"])


class SetReadOnly(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, folder)
        self.file = folder / "HCR-00001-001_A.SLDPRT"
        self.file.write_bytes(b"x")

    def test_a_writable_file_becomes_read_only(self):
        read_only._set_read_only(self.file)
        self.assertFalse(os.stat(self.file).st_mode & stat.S_IWUSR)

    @unittest.skipIf(os.name == "nt", "Windows has no ctime to change (st_ctime is when the file was made)")
    def test_a_read_only_file_is_left_alone(self):
        os.chmod(self.file, stat.S_IREAD)
        before = os.stat(self.file).st_ctime_ns
        time.sleep(0.02)
        read_only._set_read_only(self.file)
        self.assertEqual(os.stat(self.file).st_ctime_ns, before)

    def test_a_missing_file_or_a_folder_is_left_alone(self):
        read_only._set_read_only(self.file.with_name("missing"))
        read_only._set_read_only(self.file.parent)
        self.assertTrue(os.stat(self.file.parent).st_mode & stat.S_IWUSR)


if __name__ == "__main__":
    unittest.main()
