"""Tests for Update references (reference_replace). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import PART, PRT, git
from litterbox.references import reference_queries
from litterbox.references import reference_reader
from litterbox.references import reference_replace
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from tests.support.references_fixture import ASM, ASM_FILE, PRT_B, STEM_A, STEM_B, RefsFixture


class TestReplace(RefsFixture, unittest.TestCase):
    def test_replace_checks_out_edits_checks_in_and_updates_the_record(self):
        self.release_part_rev_b()
        (result,) = self.replace()
        self.assertEqual((result.parent, result.status), (ASM, "done"), result.message)
        text = (self.a / ASM_FILE).read_text()
        self.assertIn(f"ref: {self.a / PRT_B}", text)
        self.assertNotIn(f"ref: {self.a / PRT}\n", text)
        self.assertEqual(self.record().references, {"A": [STEM_B]})
        self.assertEqual(self.locks(self.a), {})
        self.assertIn("HCR-00002-001: Updated to the latest released parts", self.remote_log())
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(reference_queries.stale_everywhere(self.a), [])
        self.assertEqual(reference_queries.where_used(self.a, PART)[0].child_revision, "B")

    def test_assembly_checked_out_by_someone_else_is_skipped(self):
        self.release_part_rev_b()
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            checkout.checkout(self.b, ASM)
        (result,) = self.replace()
        self.assertEqual(result.status, "skipped")
        self.assertIn("Bea", result.message)
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_assembly_you_have_checked_out_is_changed_but_left_for_you_to_check_in(self):
        self.release_part_rev_b()
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
        (result,) = self.replace()
        self.assertEqual(result.status, "left_checked_out")
        self.assertIn(f"ref: {self.a / PRT_B}", (self.a / ASM_FILE).read_text())
        self.assertEqual(self.record().references, {"A": [STEM_A]})             # not yet
        with self.user("Alex"):
            checkin.checkin(self.a, ASM, "Take new part", references_reader=reference_reader.make_reader(self.fake))
        self.assertEqual(self.record().references, {"A": [STEM_B]})

    def test_a_failure_undoes_the_checkout_and_leaves_the_assembly_alone(self):
        self.release_part_rev_b()
        self.fake.refuse_repoint = True
        (result,) = self.replace()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.locks(self.a), {})
        self.assertIn(f"ref: {self.a / PRT}", (self.a / ASM_FILE).read_text())
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_released_assemblies_and_up_to_date_references_are_never_in_the_list(self):
        self.assertEqual(reference_replace.replacements_from(reference_queries.uses(self.a, ASM)), [])
        self.release_part_rev_b()
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)
        self.assertEqual(reference_queries.stale_everywhere(self.a), [])

    def test_replace_refuses_a_part_whose_new_file_is_not_downloaded(self):
        self.release_part_rev_b()
        items = [reference_replace.Replacement(ASM, PART, "A")]
        pointer = self.a / PRT_B
        pointer.chmod(0o644)                                  # a part that isn't checked out is read-only on disk
        pointer.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:00\nsize 1\n")
        (result,) = reference_replace.replace_references(self.a, items, backend=self.fake, log=self.log.append)
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
