"""Tests for pn.py. Run from the app folder with:  python -m unittest discover -s tests -v"""

import unittest

import pn as pn_module
from pn import (PN, PNError, filename, lowest_unused, next_base, next_variant,
                parse, parse_filename, try_parse, try_parse_filename)


class TestBuildAndParse(unittest.TestCase):
    def test_str_pads_numbers(self):
        self.assertEqual(str(PN("HCR", 42, 1)), "HCR-00042-001")

    def test_org_is_uppercased(self):
        self.assertEqual(PN("hcr", 1, 1).org, "HCR")

    def test_text_numbers_are_accepted(self):
        self.assertEqual(PN("HCR", "00042", "001"), PN("HCR", 42, 1))

    def test_parse_round_trip(self):
        self.assertEqual(str(parse("HCR-00042-001")), "HCR-00042-001")

    def test_parse_accepts_lowercase(self):
        self.assertEqual(parse("hcr-00042-001"), PN("HCR", 42, 1))

    def test_six_digit_base_is_fine(self):
        pn = parse("HCR-100000-001")
        self.assertEqual(pn.base, 100000)
        self.assertEqual(str(pn), "HCR-100000-001")

    def test_bad_part_numbers(self):
        for bad in ["", "HCR-42-001", "H-00042-001", "HCRDE-00042-001", "HCR-00042-1",
                    "HCR-00042-0001", "HCR-00042-001_A.SLDPRT", "HCR_00042_001",
                    "HCR-00000-001", "HCR-00042-000"]:
            with self.subTest(bad=bad):
                with self.assertRaises(PNError):
                    parse(bad)
                self.assertIsNone(try_parse(bad))

    def test_variant_limits(self):
        PN("HCR", 1, 1)
        PN("HCR", 1, 999)
        for bad in (0, 1000, -1):
            with self.assertRaises(PNError):
                PN("HCR", 1, bad)

    def test_base_must_be_positive(self):
        for bad in (0, -5, "abc", 1.5, True):
            with self.assertRaises(PNError):
                PN("HCR", bad, 1)

    def test_bad_org(self):
        for bad in ("", "A", "ABCDE", "H1R", "12"):
            with self.assertRaises(PNError):
                PN(bad, 1, 1)

    def test_pns_sort_in_order(self):
        pns = [PN("HCR", 2, 1), PN("HCR", 1, 2), PN("HCR", 1, 1)]
        self.assertEqual([str(p) for p in sorted(pns)],
                         ["HCR-00001-001", "HCR-00001-002", "HCR-00002-001"])

    def test_pns_work_in_sets(self):
        self.assertEqual(len({PN("HCR", 1, 1), PN("hcr", "00001", "001")}), 1)


class TestFilenames(unittest.TestCase):
    def test_parse_filename(self):
        self.assertEqual(parse_filename("HCR-00042-001_A.SLDPRT"), (PN("HCR", 42, 1), "A", "SLDPRT"))
        self.assertEqual(parse_filename("HCR-00042-001_AB.SLDPRT")[1], "AB")

    def test_lowercase_filename(self):
        self.assertEqual(parse_filename("hcr-00042-001_b.sldprt"), (PN("HCR", 42, 1), "B", "SLDPRT"))

    def test_a_file_without_a_revision_is_not_a_litterbox_file(self):
        self.assertIsNone(try_parse_filename("HCR-00042-001.SLDPRT"))
        self.assertIsNone(try_parse_filename("HCR-00042-001_1.SLDPRT"))
        self.assertIsNone(try_parse_filename("HCR-00042-001_ABCD.SLDPRT"))
        with self.assertRaises(PNError) as ctx:
            parse_filename("HCR-00042-001.SLDPRT")
        self.assertIn("_A", str(ctx.exception))

    def test_folders_are_ignored(self):
        expected = (PN("HCR", 42, 1), "A", "SLDDRW")
        self.assertEqual(parse_filename("cad/HCR-00042-001_A.SLDDRW"), expected)
        self.assertEqual(parse_filename("C:\\Litterbox\\hcr-litterbox\\cad\\HCR-00042-001_A.SLDDRW"), expected)

    def test_not_litterbox_files(self):
        for bad in ["notes.txt", "~$HCR-00042-001_A.SLDPRT", "HCR-00042-001", "HCR-00042-001.",
                    "HCR-00042-001_A.SLDPRT.bak"]:
            with self.subTest(bad=bad):
                with self.assertRaises(PNError):
                    parse_filename(bad)
                self.assertIsNone(try_parse_filename(bad))

    def test_build_filename(self):
        self.assertEqual(filename(PN("HCR", 42, 1), "a", "sldprt"), "HCR-00042-001_A.SLDPRT")
        self.assertEqual(filename(PN("HCR", 42, 1), "B", ".SLDDRW"), "HCR-00042-001_B.SLDDRW")
        self.assertEqual(pn_module.file_stem(PN("HCR", 42, 1)), "HCR-00042-001_A")
        self.assertEqual(pn_module.file_stem(PN("HCR", 42, 1), "c"), "HCR-00042-001_C")


class TestShortAndRevisions(unittest.TestCase):
    def test_short_form_leaves_out_the_org(self):
        self.assertEqual(PN("HCR", 42, 1).short, "00042-001")
        self.assertEqual(pn_module.parse_short("00042-001", "hcr"), PN("HCR", 42, 1))
        self.assertEqual(pn_module.parse_short("HCR-00042-001", "xyz"), PN("HCR", 42, 1))   # a full PN still reads
        for bad in ("42-1", "00042", "abc"):
            with self.assertRaises(PNError):
                pn_module.parse_short(bad, "HCR")

    def test_revision_letters_count_up(self):
        self.assertEqual([pn_module.revision_label(n) for n in (1, 2, 26, 27, 28, 52, 53)],
                         ["A", "B", "Z", "AA", "AB", "AZ", "BA"])
        self.assertEqual([pn_module.revision_number(x) for x in ("A", "z", "AA", "ba")], [1, 26, 27, 53])
        self.assertEqual(pn_module.next_revision("A"), "B")
        self.assertEqual(pn_module.next_revision("Z"), "AA")

    def test_cancelled_letters_are_skipped(self):
        self.assertEqual(pn_module.next_revision("A", skip=["B"]), "C")
        self.assertEqual(pn_module.next_revision("A", skip=["B", "C"]), "D")

    def test_bad_revisions_are_refused(self):
        for bad in ("", "1", "ABCD", "A1"):
            with self.assertRaises(PNError):
                pn_module.check_revision(bad)
        self.assertEqual(pn_module.check_revision(" b "), "B")


class TestLowestUnused(unittest.TestCase):
    def test_empty_starts_at_one(self):
        self.assertEqual(next_base(set()), 1)
        self.assertEqual(next_variant(set()), 1)

    def test_continues_sequence(self):
        self.assertEqual(next_base({1, 2, 3}), 4)

    def test_fills_gaps_lowest_first(self):
        self.assertEqual(next_base({2, 3}), 1)
        self.assertEqual(next_base({1, 3, 4}), 2)

    def test_manually_entered_number_is_skipped_when_reached(self):
        used = {500}
        self.assertEqual(next_base(used), 1)
        used = set(range(1, 500)) | {500}
        self.assertEqual(next_base(used), 501)

    def test_start_number_sets_the_first_number(self):
        self.assertEqual(next_base(set(), 10001), 10001)
        self.assertEqual(next_base({10001, 10002}, 10001), 10003)
        self.assertEqual(next_base({1, 2, 3}, 10001), 10001)        # older numbers don't matter
        self.assertEqual(next_base({10001, 10003}, 10001), 10002)   # gaps above the start still fill
        self.assertEqual(next_base(set(), 0), 1)                    # never below the minimum

    def test_accepts_any_iterable(self):
        self.assertEqual(next_base([1, 2, 2, 3]), 4)

    def test_variants_run_out_at_999(self):
        self.assertEqual(next_variant(set(range(1, 999))), 999)
        with self.assertRaises(PNError):
            next_variant(set(range(1, 1000)))

    def test_lowest_unused_generic(self):
        self.assertEqual(lowest_unused({5, 6}, 5), 7)


class TestConfigurableDigits(unittest.TestCase):
    def setUp(self):
        self.addCleanup(pn_module.configure)          # always put the defaults back

    def test_defaults_are_five_and_three(self):
        self.assertEqual((pn_module.BASE_DIGITS, pn_module.VARIANT_DIGITS), (5, 3))
        self.assertEqual(str(PN("HCR", 42, 1)), "HCR-00042-001")

    def test_other_digit_counts_change_the_format_and_the_limits(self):
        pn_module.configure(6, 2)
        self.assertEqual(str(PN("HCR", 42, 1)), "HCR-000042-01")
        self.assertEqual(pn_module.parse("hcr-000042-01"), PN("HCR", 42, 1))
        self.assertEqual(pn_module.parse_filename("cad/HCR-000042-01_a.sldprt"), (PN("HCR", 42, 1), "A", "SLDPRT"))
        self.assertEqual(pn_module.MAX_VARIANT, 99)
        with self.assertRaises(PNError):
            PN("HCR", 42, 100)
        with self.assertRaises(PNError):
            pn_module.parse("HCR-00042-001")                  # the old format no longer reads
        self.assertEqual(next_variant(set(range(1, 99))), 99)
        with self.assertRaises(PNError):
            next_variant(set(range(1, 100)))

    def test_bases_with_extra_digits_still_read_but_cannot_be_created(self):
        self.assertEqual(pn_module.parse("HCR-123456-001").base, 123456)
        with self.assertRaises(PNError) as ctx:
            pn_module.check_new_base(100000)
        self.assertIn("99999", str(ctx.exception))
        self.assertEqual(pn_module.check_new_base(99999), 99999)

    def test_bad_digit_counts_are_refused(self):
        for base, variant in ((0, 3), (10, 3), (5, 0), (5, 5), (True, 3), ("5", 3)):
            with self.subTest(base=base, variant=variant), self.assertRaises(PNError):
                pn_module.configure(base, variant)
        self.assertEqual((pn_module.BASE_DIGITS, pn_module.VARIANT_DIGITS), (5, 3))     # unchanged


if __name__ == "__main__":
    unittest.main()


class TestWrapAround(unittest.TestCase):
    """Part numbers count up from the start number, then loop round to 1 and stop just below the start."""

    def setUp(self):
        pn_module.configure(base_digits=3)               # 1..999
        self.addCleanup(pn_module.configure)

    def test_after_the_highest_number_it_starts_again_at_one(self):
        self.assertEqual(next_base({900, 901, 999}, 900), 902)
        self.assertEqual(next_base(set(range(900, 1000)), 900), 1)
        self.assertEqual(next_base(set(range(900, 1000)) | {1, 2}, 900), 3)

    def test_zero_is_never_used(self):
        self.assertNotIn(0, list(pn_module.base_order(900)))
        self.assertEqual(list(pn_module.base_order(900))[:2], [900, 901])
        self.assertEqual(list(pn_module.base_order(900))[100], 1)
        self.assertEqual(len(list(pn_module.base_order(900))), 999)

    def test_the_start_number_is_only_the_first_point_of_the_loop(self):
        order = list(pn_module.base_order(500))
        self.assertEqual(order[0], 500)
        self.assertEqual(order[-1], 499)
        self.assertEqual(sorted(order), list(range(1, 1000)))

    def test_the_numbers_below_the_start_are_used_last(self):
        self.assertEqual(next_base({1, 2, 3}, 900), 900)           # free numbers above the start come first
        self.assertEqual(next_base(set(range(900, 1000)) | {1}, 900), 2)

    def test_a_start_that_does_not_fit_in_the_digits_means_start_at_one(self):
        self.assertEqual(next_base(set(), 5000), 1)

    def test_free_bases_gives_the_lowest_free_ones_in_order(self):
        self.assertEqual(pn_module.free_bases({900, 902}, 4, 900), [901, 903, 904, 905])
        self.assertEqual(pn_module.free_bases(set(range(900, 1000)) | {2}, 3, 900), [1, 3, 4])
        self.assertEqual(pn_module.free_bases(set(), 0), [])

    def test_a_full_vault_says_so(self):
        with self.assertRaises(pn_module.PNError) as caught:
            next_base(set(range(1, 1000)), 900)
        self.assertIn("no part numbers left", str(caught.exception))
        self.assertEqual(pn_module.free_bases(set(range(1, 997)), 5, 900), [997, 998, 999])      # fewer than asked


class TestBaseAfter(unittest.TestCase):
    def setUp(self):
        pn_module.configure(base_digits=3)               # 1..999
        self.addCleanup(pn_module.configure)

    def test_steps_along_the_loop(self):
        self.assertEqual(pn_module.base_after(10, 100), 110)
        self.assertEqual(pn_module.base_after(999, 1), 1)                  # past the top, back round to 1
        self.assertEqual(pn_module.base_after(5, 0, 900), 5)
        self.assertEqual(pn_module.base_after(900, 99, 900), 999)
        self.assertEqual(pn_module.base_after(900, 100, 900), 1)           # zero is skipped
        self.assertEqual(pn_module.base_after(898, 1, 900), 899)           # the last number of the loop
        self.assertEqual(pn_module.base_after(899, 1, 900), 900)           # and round to the start again
