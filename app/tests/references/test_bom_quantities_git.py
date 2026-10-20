"""Tests for counting an assembly's parts at check-in and with Update BOM, in a real vault. They need Linux, macOS
or WSL."""

import unittest
from tests.support.vault_fixture import PRT, git
from litterbox.git import lfs_locks
from litterbox.git import read_only
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.records import record_store
from litterbox.references import reference_reader
from litterbox.references import reference_rescan
from tests.support.references_fixture import ASM, ASM_FILE, STEM_A, RefsFixture

RECORD = "PN-logs/HCR-00002-001.yaml"


class TestCountingParts(RefsFixture, unittest.TestCase):
    def check_in(self, text, closed=False):
        self.fake.closed = closed
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(text, encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=reference_reader.make_reader(self.fake, self.log.append))
        self.fake.closed = False

    def edit_record(self, change):
        """Change the assembly's record by hand (as an older Litterbox would leave it) and upload it."""
        with self.user("Alex"):
            lfs_locks.lock(self.a, RECORD, ASM)
            record = record_store.load(self.a, ASM)
            change(record)
            record_store.save(self.a, record)
            git(self.a, "commit", "-am", "edit by hand")
            git(self.a, "push")
            lfs_locks.unlock_mine(self.a, [RECORD])
            read_only.enforce_read_only(self.a)

    def rescan(self):
        with self.user("Alex"):
            return reference_rescan.rescan(self.a, [ASM], backend=self.fake, log=self.log.append)

    def test_check_in_counts_each_copy_and_leaves_out_suppressed_ones(self):
        self.assertEqual(self.record().quantities, {"A": {STEM_A: 1}})
        self.check_in(f"assembly\nref: {self.a / PRT}\nref: {self.a / PRT}\nref: {self.a / PRT}\n"
                      f"suppressed: {self.a / PRT}\n")
        self.assertEqual(self.record().quantities, {"A": {STEM_A: 3}})
        with self.user("Alex"):
            row = self.status_of(self.a, ASM)
        self.assertFalse(row.bom_outdated)
        self.assertNotIn("needs updating", row.state)

    def test_without_solidworks_the_check_in_goes_ahead_and_update_fixes_it(self):
        self.check_in(f"assembly, edited\nref: {self.a / PRT}\nref: {self.a / PRT}\n", closed=True)
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")             # it was uploaded
        self.assertEqual((self.record().quantities, self.record().references_outdated), ({}, ["A"]))
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            row = self.status_of(self.b, ASM)
        self.assertTrue(row.bom_outdated)
        self.assertIn("(references need updating)", row.state)
        self.assertEqual(self.rescan(), {ASM: "updated"})
        self.assertEqual((self.record().quantities, self.record().references_outdated), ({"A": {STEM_A: 2}}, []))
        with self.user("Alex"):
            self.assertFalse(self.status_of(self.a, ASM).bom_outdated)

    def test_a_bom_counted_by_no_one_says_it_needs_updating_until_it_is(self):
        self.edit_record(lambda record: setattr(record, "quantities", {}))
        with self.user("Alex"):
            row = self.status_of(self.a, ASM)
        self.assertTrue(row.bom_outdated)
        self.assertIn("(BOM needs updating)", row.state)
        self.assertEqual(self.rescan(), {ASM: "updated"})
        record = self.record()
        self.assertEqual(record.quantities, {"A": {STEM_A: 1}})
        self.assertEqual(record.history[-1]["quantities"], {"A": {STEM_A: 1}})
        self.assertEqual(self.rescan(), {ASM: "unchanged"})

    def test_a_part_whose_file_is_missing_is_not_counted(self):
        self.edit_record(lambda record: setattr(record, "quantities", {}))
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(f"assembly\nref: {self.a / PRT}\nsuppressed: /gone/HCR-00009-001_A.SLDPRT\n",
                                           encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit")
        result = self.rescan()[ASM]                        # its references are read again; its parts aren't counted
        self.assertTrue(result.startswith("updated, but its parts could not be counted"), result)
        self.assertEqual((self.record().quantities, self.record().references_outdated), ({}, []))
        self.assertTrue(self.rescan()[ASM].startswith("skipped: its parts could not be counted"))


if __name__ == "__main__":
    unittest.main()
