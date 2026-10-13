"""
Tests for file_snapshot.py: noticing that a file was saved after Check In was pressed. These use plain files, no vault.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import file_snapshot as fs  # noqa: E402

PART = "HCR-00002-001"
FILES = ["cad/HCR-00002-001_A.SLDPRT", "cad/HCR-00002-001_A.SLDDRW"]


class Snapshots(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        (self.repo / "cad").mkdir()
        for rel in FILES:
            (self.repo / rel).write_bytes(b"version one")
        self.snap = fs.FileSnapshot(self.repo, {PART: FILES})
        self.addCleanup(self.snap.release)

    def touch(self, rel, content=None, seconds=5):
        path = self.repo / rel
        if content is not None:
            path.write_bytes(content)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + seconds * 1_000_000_000))

    def test_nothing_changed_means_no_problems(self):
        self.assertEqual(self.snap.problems(PART, FILES), [])
        self.assertTrue(self.snap.covers(PART))
        self.assertFalse(self.snap.covers("HCR-00009-001"))

    def test_a_save_with_a_different_size_is_noticed(self):
        (self.repo / FILES[0]).write_bytes(b"version two, longer")
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[0]])

    def test_a_save_with_the_same_size_is_noticed_by_the_time(self):
        self.touch(FILES[1], b"version ONE", seconds=3)           # same length
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[1]])

    def test_a_new_file_or_a_missing_file_counts(self):
        new = "cad/HCR-00002-001_A.STEP"
        (self.repo / new).write_bytes(b"x")
        self.assertEqual(self.snap.problems(PART, FILES + [new]), [new])
        (self.repo / FILES[0]).unlink()
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[0]])

    def test_a_download_that_rewrites_your_files_is_not_a_save(self):
        fs.before_pull(self.repo)
        self.touch(FILES[0], seconds=7)                           # git rewrote it with the same contents
        fs.after_pull(self.repo)
        self.assertEqual(self.snap.problems(PART, FILES), [])

    def test_a_save_before_a_download_is_still_noticed_after_it(self):
        self.touch(FILES[0], b"version TWO!!", seconds=2)         # the user saved
        fs.before_pull(self.repo)
        self.touch(FILES[0], seconds=9)                           # then the download rewrote it
        fs.after_pull(self.repo)
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[0]])

    def test_a_save_after_a_download_is_noticed(self):
        fs.before_pull(self.repo)
        fs.after_pull(self.repo)
        (self.repo / FILES[1]).write_bytes(b"saved later, longer")
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[1]])

    def test_releasing_stops_the_watching(self):
        self.snap.release()
        self.touch(FILES[0], b"changed!!!!")
        fs.before_pull(self.repo)
        self.assertEqual(self.snap.changed, set())

    def test_other_vaults_are_left_alone(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        self.touch(FILES[0], b"changed!!!!")
        fs.before_pull(other.name)
        fs.after_pull(other.name)
        self.assertEqual(self.snap.problems(PART, FILES), [FILES[0]])

    def test_stats_and_moved(self):
        before = fs.stats(self.repo, FILES)
        self.assertEqual(fs.moved(self.repo, before), [])
        self.touch(FILES[1], b"different length!")
        self.assertEqual(fs.moved(self.repo, before), [FILES[1]])
        self.assertEqual(fs.names(FILES), "HCR-00002-001_A.SLDDRW, HCR-00002-001_A.SLDPRT")

    def test_looking_costs_next_to_nothing(self):
        import time
        many = [f"cad/HCR-{n:05d}-001_A.SLDPRT" for n in range(2000)]
        for rel in many:
            (self.repo / rel).write_bytes(b"x")
        started = time.monotonic()
        snap = fs.FileSnapshot(self.repo, {"all": many})
        snap.problems("all", many)
        snap.release()
        self.assertLess(time.monotonic() - started, 2.0)          # a very loose bound: 4000 metadata lookups


class Wiring(unittest.TestCase):
    def test_the_window_takes_the_snapshot_when_check_in_is_queued(self):
        source = (Path(__file__).resolve().parent.parent / "litterbox_gui.py").read_text(encoding="utf-8")
        self.assertIn("snapshot = self._watch_files(plan.targets)", source)
        self.assertIn("snapshot=snapshot))", source)
        self.assertIn("engine.watch_files(", source)


if __name__ == "__main__":
    unittest.main()
