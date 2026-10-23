"""Tests for Vault > Vault Size...: reading what git and Git LFS say, and the words shown. Git itself is replaced."""

import json
import tempfile
import unittest
from pathlib import Path

from litterbox.errors import LitterboxError
from litterbox.git import runner
from litterbox.git import vault_size
from litterbox.gui.logic import vault_size_text
from tests.support import temp_folders

COUNT_OBJECTS = "count: 202\nsize: 58\nin-pack: 10\npacks: 1\nsize-pack: 100\nprune-packable: 0\n"
LS_FILES = json.dumps({"files": [{"name": "cad/a_A.SLDPRT", "size": 1000, "oid": "ab" + "0" * 62},
                                 {"name": "cad/a_B.SLDPRT", "size": 3000, "oid": "cd" + "1" * 62},
                                 {"name": "cad/b_A.SLDPRT", "size": 1000, "oid": "ab" + "0" * 62}]})


class Reading(unittest.TestCase):
    def test_history_and_lfs_objects_are_read_and_each_object_counted_once(self):
        self.assertEqual(vault_size.history_bytes(COUNT_OBJECTS), 158 * 1024)
        self.assertEqual(vault_size.lfs_objects(LS_FILES), {"ab" + "0" * 62: 1000, "cd" + "1" * 62: 3000})
        self.assertEqual(vault_size.lfs_objects(""), {})
        with self.assertRaisesRegex(LitterboxError, "3.4 or newer"):
            vault_size.lfs_objects("Error: unknown flag: --json")

    def test_measure_fetches_then_counts_what_is_downloaded_here(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, repo)
        here = repo / ".git" / "lfs" / "objects" / "cd" / "11" / ("cd" + "1" * 62)
        here.parent.mkdir(parents=True)
        here.write_bytes(b"x")
        answers = {"fetch": "", "rev-list": "27\n", "count-objects": COUNT_OBJECTS, "lfs": LS_FILES}
        ran = []

        def fake_run(command, folder, quiet=False):
            ran.append(command[1])
            if command[1] == "fetch" and self.offline:
                raise LitterboxError("could not reach the host")
            return answers[command[1]]

        original = runner.run
        self.addCleanup(setattr, runner, "run", original)
        runner.run = fake_run
        self.offline = False
        size = vault_size.measure(repo)
        self.assertEqual(ran[0], "fetch")
        self.assertEqual((size.commits, size.lfs_files, size.lfs_bytes), (27, 2, 4000))
        self.assertEqual((size.downloaded_files, size.downloaded_bytes, size.fetched), (1, 3000, True))
        self.offline = True
        self.assertFalse(vault_size.measure(repo).fetched)


class Words(unittest.TestCase):
    def test_sizes_read_at_a_glance(self):
        self.assertEqual(vault_size_text.readable(900), "900 bytes")
        self.assertEqual(vault_size_text.readable(1536), "1.5 KB")
        self.assertEqual(vault_size_text.readable(32_296_141), "30.8 MB")

    def test_the_window_text(self):
        size = vault_size.VaultSize(27, 62_464, 32, 32_296_141, 1, 1000, fetched=False)
        text = vault_size_text.size_text(size)
        self.assertTrue(text.startswith("Stored on the host: about 30.9 MB"))
        self.assertIn("History (27 commits", text)
        self.assertIn("(32 file versions): 30.8 MB", text)
        self.assertIn("1 file version, 1000 bytes", text)
        self.assertIn("couldn't be reached", text)


if __name__ == "__main__":
    unittest.main()
