"""Tests for importing every part as a variant of one base number (import_numbering.set_family and friends), and
for assemblies getting the assembly variants (from 500) as New Assembly does. The vault (a stand-in) uses the default
3-digit variants, so parts take 001 to 499 and assemblies 500 to 999."""

import unittest
from types import SimpleNamespace
from unittest import mock


from litterbox.parts import create_batch
from litterbox.importing import import_errors
from litterbox.importing import import_numbering
from litterbox.importing import import_prepare
from litterbox.core import part_number
from litterbox.records import record_store
from litterbox.core.part_number import PN


def entry(base, variant=1, manual=False, kind="part"):
    return import_numbering.Entry(SimpleNamespace(kind=kind), PN("HCR", base, variant), "part", manual=manual)


class FamilyNumbering(unittest.TestCase):
    def setUp(self):
        self.existing = []
        for target, value in ((record_store, "list_pns"), (create_batch, "sync_latest")):
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
        return import_numbering.Proposal(list(entries), "HCR")

    def test_a_new_base_starts_at_variant_one(self):
        p = self.proposal(entry(10), entry(20), entry(30))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00042-001", "HCR-00042-002", "HCR-00042-003"])
        self.assertEqual(p.family, 42)

    def test_an_existing_base_continues_from_the_lowest_free_variant(self):
        self.existing = [PN("HCR", 42, 1), PN("HCR", 42, 2), PN("HCR", 42, 4), PN("HCR", 7, 3)]
        p = self.proposal(entry(10), entry(20), entry(30))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual([e.pn.variant for e in p.entries], [3, 5, 6])

    def test_typed_numbers_are_left_alone_and_their_variants_skipped(self):
        p = self.proposal(entry(10), entry(42, 1, manual=True), entry(30))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00042-002", "HCR-00042-001", "HCR-00042-003"])

    def test_too_many_parts_for_the_variants_left_is_refused_and_changes_nothing(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 498)]          # 2 part variants free: 498 and 499
        p = self.proposal(entry(10), entry(20), entry(30))
        before = [str(e.pn) for e in p.entries]
        with self.assertRaises(import_errors.FamilyFull) as caught:
            import_numbering.set_family("repo", p, 42)
        self.assertIn("2 unused variant number(s) for parts (001 to 499)", str(caught.exception))
        self.assertEqual([str(e.pn) for e in p.entries], before)
        self.assertIsNone(p.family)

    def test_exactly_enough_room_is_allowed(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 498)]
        p = self.proposal(entry(10), entry(20))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual([e.pn.variant for e in p.entries], [498, 499])         # parts never spill into 500 and up

    def test_assemblies_in_a_family_take_the_assembly_variants(self):
        self.existing = [PN("HCR", 42, 500)]
        p = self.proposal(entry(10, kind="assembly"), entry(20), entry(30, kind="assembly"), entry(40))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual([e.pn.variant for e in p.entries], [501, 1, 502, 2])
        self.assertEqual(str(import_prepare.free_pn("repo", p, SimpleNamespace(kind="assembly"))), "HCR-00042-503")
        self.assertEqual(str(import_prepare.free_pn("repo", p, SimpleNamespace(kind="part"))), "HCR-00042-003")

    def test_too_many_assemblies_says_which_variants_ran_out(self):
        self.existing = [PN("HCR", 42, v) for v in range(500, 999)]          # only 999 left for assemblies
        p = self.proposal(entry(10, kind="assembly"), entry(20, kind="assembly"))
        with self.assertRaises(import_errors.FamilyFull) as caught:
            import_numbering.set_family("repo", p, 42)
        self.assertIn("1 unused variant number(s) for assemblies (500 to 999), but 2 assemblies", str(caught.exception))

    def test_an_automatic_row_never_shares_a_base_with_another_part(self):
        self.existing = [PN("HCR", 3, 1)]                                   # someone's part on base 3
        p = self.proposal(entry(3, 500, kind="assembly"), entry(4), entry(4, 500, kind="assembly"),
                          entry(3, 2, manual=True))
        reasons = {c.index: c.reason for c in import_numbering.check_proposal("repo", p)}
        self.assertIn("00003 is already used in the vault", reasons[0])
        self.assertIn("already used in this import (row 2)", reasons[2])
        self.assertNotIn(3, reasons)                                       # typed: only its own variant counts
        self.assertNotIn(1, reasons)

    def test_separate_numbers_give_an_assembly_variant_500(self):
        p = self.proposal(entry(10), entry(20, kind="assembly"))
        import_numbering.set_family("repo", p, 42)
        with mock.patch.object(import_numbering, "pick_block",
                               return_value=[PN("HCR", 100, 1), PN("HCR", 101, 1)]):
            import_numbering.set_family("repo", p, None)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00100-001", "HCR-00101-500"])

    def test_an_invalid_base_is_refused(self):
        p = self.proposal(entry(10))
        for bad in ("abc", "0", 10 ** 6):
            with self.assertRaises(import_errors.ImportFailed):
                import_numbering.set_family("repo", p, bad)

    def test_typed_text_works_like_a_number(self):
        p = self.proposal(entry(10))
        import_numbering.set_family("repo", p, "00042")
        self.assertEqual(str(p.entries[0].pn), "HCR-00042-001")

    def test_turning_it_off_gives_separate_numbers_again(self):
        p = self.proposal(entry(10), entry(20))
        import_numbering.set_family("repo", p, 42)
        with mock.patch.object(import_numbering, "pick_block",
                               return_value=[PN("HCR", 100, 1), PN("HCR", 101, 1)]):
            import_numbering.set_family("repo", p, None)
        self.assertEqual([str(e.pn) for e in p.entries], ["HCR-00100-001", "HCR-00101-001"])
        self.assertIsNone(p.family)

    def test_a_row_added_later_gets_the_next_free_variant(self):
        p = self.proposal(entry(10), entry(20))
        import_numbering.set_family("repo", p, 42)
        self.assertEqual(str(import_prepare.free_pn("repo", p)), "HCR-00042-003")

    def test_a_row_added_when_the_base_is_full_is_refused(self):
        self.existing = [PN("HCR", 42, v) for v in range(1, 499)]          # only 499 free for parts
        p = self.proposal(entry(10))
        import_numbering.set_family("repo", p, 42)
        with self.assertRaises(import_errors.FamilyFull):
            import_prepare.free_pn("repo", p)

    def test_a_variant_taken_in_the_meantime_moves_to_the_next_free_one(self):
        p = self.proposal(entry(10), entry(20))
        import_numbering.set_family("repo", p, 42)
        self.existing = [PN("HCR", 42, 2)]                                  # somebody just took 002
        state = import_numbering.refresh("repo", p, log=lambda text: None)
        self.assertEqual([e.pn.variant for e in p.entries], [1, 3])
        self.assertEqual(len(state.renumbered), 1)
        self.assertEqual(state.conflicts, [])


if __name__ == "__main__":
    unittest.main()
