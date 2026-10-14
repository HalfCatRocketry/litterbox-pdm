"""Tests for reading every assembly's references again (reference_rescan). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import git
from litterbox.references import reference_rescan
from litterbox.records import record_store
from litterbox.git import lfs_locks
from litterbox.git import read_only
from tests.support.references_fixture import ASM, STEM_A, RefsFixture


class TestRescan(RefsFixture, unittest.TestCase):
    def test_rescan_fills_in_records_that_have_no_references(self):
        record_path = self.a / "PN-logs" / "HCR-00002-001.yaml"
        with self.user("Alex"):
            lfs_locks.lock(self.a, "PN-logs/HCR-00002-001.yaml", ASM)
            record = record_store.load(self.a, ASM)
            record.references = {}
            record_store.save(self.a, record)
            git(self.a, "commit", "-am", "forget the references")
            git(self.a, "push")
            lfs_locks.unlock_mine(self.a, ["PN-logs/HCR-00002-001.yaml"])
            read_only.enforce_read_only(self.a)
            result = reference_rescan.rescan(self.a, backend=self.fake, log=self.log.append)
        self.assertEqual(result, {ASM: "updated"})
        self.assertEqual(self.record().references, {"A": [STEM_A]})
        with self.user("Alex"):
            self.assertEqual(reference_rescan.rescan(self.a, backend=self.fake, log=self.log.append), {ASM: "unchanged"})
        self.assertTrue(record_path.exists())


if __name__ == "__main__":
    unittest.main()
