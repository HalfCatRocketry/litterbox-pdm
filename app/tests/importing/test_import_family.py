"""Tests for importing every part as a variant of one base number (importer.set_family and friends)."""

import unittest
from types import SimpleNamespace
from unittest import mock


from litterbox.parts import create
from litterbox.importing import importer
from litterbox.core import part_number
from litterbox.records import registry
from litterbox.core.part_number import PN


def entry(base, variant=1, manual=False):
    return importer.Entry(SimpleNamespace(), PN("HCR", base, variant), "part", manual=manual)


class FamilyNumbering(unittest.TestCase):
    def setUp(self):
        self.existing = []
        for target, value in ((registry, "list_pns"), (create, "sync_latest")):
            patcher = mock.patch.object(target, value, side_effect=self._fake(value))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(part_number, "MAX_VARIANT", 999)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake(self, name):
        if name == "list_pns":
            return lambda repo, org=None: list(self.existing)
        return lambda repo: None

    def proposal(self, *entries):
        return importer.Proposal(list(entries), "HCR")

    def test_a_new_base_starts_at_variant_one(self):
        p = self.proposal(entry(10), entry(20), entry(30))
        importer.set_family("repo", p, 42)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00042-001", "HCR-00042-002", "HCR-00042-003"])
        self.assertEqual(p.family, 42)

    def test_an_existing_base_continues_from_the_lowest_free_variant(self):
        self.existing = [PN("HCR", 42, 1), PN("HCR", 42, 2), PN("HCR", 42, 4), PN("HCR", 7, 3)]
        p = self.proposal(entry(10), entry(20), entry(30))
        importer.set_family("repo", p, 42)
        self.assertEqual([e.pn.variant for e in p.entries], [3, 5, 6])

    def test_typed_numbers_are_left_alone_and_their_variants_skipped(self):
        p = self.proposal(entry(10), entry(42, 1, manual=True), entry(30))
        importer.set_family("repo", p, 42)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00042-002", "HCR-00042-001", "HCR-00042-003"])

    def test_too_many_parts_for_the_variants_left_is_refused_and_changes_nothing(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 998)]          # 2 free: 998 and 999
        p = self.proposal(entry(10), entry(20), entry(30))
        before = [str(e.pn) for e in p.entries]
        with self.assertRaises(importer.FamilyFull) as caught:
            importer.set_family("repo", p, 42)
        self.assertIn("2 unused variant", str(caught.exception))
        self.assertEqual([str(e.pn) for e in p.entries], before)
        self.assertIsNone(p.family)

    def test_exactly_enough_room_is_allowed(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 998)]
        p = self.proposal(entry(10), entry(20))
        importer.set_family("repo", p, 42)
        self.assertEqual([e.pn.variant for e in p.entries], [998, 999])

    def test_an_invalid_base_is_refused(self):
        p = self.proposal(entry(10))
        for bad in ("abc", "0", 10 ** 6):
            with self.assertRaises(importer.ImportFailed):
                importer.set_family("repo", p, bad)

    def test_typed_text_works_like_a_number(self):
        p = self.proposal(entry(10))
        importer.set_family("repo", p, "00042")
        self.assertEqual(str(p.entries[0].pn), "HCR-00042-001")

    def test_turning_it_off_gives_separate_numbers_again(self):
        p = self.proposal(entry(10), entry(20))
        importer.set_family("repo", p, 42)
        with mock.patch.object(importer, "pick_block",
                               return_value=[PN("HCR", 100, 1), PN("HCR", 101, 1)]):
            importer.set_family("repo", p, None)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00100-001", "HCR-00101-001"])
        self.assertIsNone(p.family)

    def test_a_row_added_later_gets_the_next_free_variant(self):
        p = self.proposal(entry(10), entry(20))
        importer.set_family("repo", p, 42)
        self.assertEqual(str(importer._free_pn("repo", p)), "HCR-00042-003")

    def test_a_row_added_when_the_base_is_full_is_refused(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 999)]          # only 999 free
        p = self.proposal(entry(10))
        importer.set_family("repo", p, 42)
        with self.assertRaises(importer.FamilyFull):
            importer._free_pn("repo", p)

    def test_a_variant_taken_in_the_meantime_moves_to_the_next_free_one(self):
        p = self.proposal(entry(10), entry(20))
        importer.set_family("repo", p, 42)
        self.existing = [PN("HCR", 42, 2)]                                  # somebody just took 002
        state = importer.refresh("repo", p, log=lambda text: None)
        self.assertEqual([e.pn.variant for e in p.entries], [1, 3])
        self.assertEqual(len(state.renumbered), 1)
        self.assertEqual(state.conflicts, [])


if __name__ == "__main__":
    unittest.main()
