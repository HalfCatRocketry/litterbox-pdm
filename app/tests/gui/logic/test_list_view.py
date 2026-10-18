"""Tests for gui/logic/list_view.py: filtering, sorting, file types, ticks and shift-click ranges."""

import unittest
from litterbox.gui.logic import list_view
from tests.support.part_rows import row, ROWS


class TestFilterRows(unittest.TestCase):
    def bases(self, **kw):
        return [r.pn.base for r in list_view.filter_rows(ROWS, **kw)]

    def test_default_hides_void(self):
        self.assertEqual(self.bases(), [1, 2, 3, 4, 6])

    def test_void_parts_have_their_own_view(self):
        self.assertEqual(self.bases(view="Void"), [5])

    def test_views(self):
        self.assertEqual(self.bases(view="Mine"), [2])
        self.assertEqual(self.bases(view="Checked out"), [2, 3])
        self.assertEqual(self.bases(view="Released"), [4])
        self.assertEqual(self.bases(view="All"), [1, 2, 3, 4, 6])
        self.assertEqual(self.bases(view="Not downloaded"), [])

    def test_not_downloaded_view_and_counts(self):
        from litterbox.parts.part_status import PartStatus
        from litterbox.core.part_number import PN
        rows = ROWS + [PartStatus(PN("HCR", 7, 1), "Stub", "in_work", "Available", "ok", not_downloaded=True)]
        self.assertEqual([r.pn.base for r in list_view.filter_rows(rows, view="Not downloaded")], [7])
        self.assertEqual(list_view.view_counts(rows), {"All": 6, "Mine": 1, "Checked out": 2, "Released": 1,
                                                       "Not downloaded": 1, "Void": 1})

    def test_search_matches_number_or_description_ignoring_case(self):
        self.assertEqual(self.bases(search="UPRIGHT"), [1, 2])
        self.assertEqual(self.bases(search="00003"), [3])
        self.assertEqual(self.bases(search="hcr-00004-001"), [4])
        self.assertEqual(self.bases(search="  pedal "), [4])
        self.assertEqual(self.bases(search="nothing like this"), [])

    def test_filters_combine(self):
        self.assertEqual(self.bases(search="upright", view="Mine"), [2])

    def test_void_hidden_even_when_searched_unless_in_the_void_view(self):
        self.assertEqual(self.bases(search="scrapped"), [])
        self.assertEqual(self.bases(search="scrapped", view="Void"), [5])

    def test_wildcards_match_the_whole_value(self):
        self.assertEqual(self.bases(search="*upright"), [1, 2])
        self.assertEqual(self.bases(search="F*t"), [1])           # "Front upright"
        self.assertEqual(self.bases(search="upr*"), [])            # must start with "upr"
        self.assertEqual(self.bases(search="hcr-0000?-001"), [1, 2, 3, 4, 6])

    def test_search_in_chosen_values_only(self):
        only_numbers = lambda r: (str(r.pn),)
        self.assertEqual(self.bases(search="upright", values=only_numbers), [])
        self.assertEqual(self.bases(search="*-00003-*", values=only_numbers), [3])


class TestFileTypes(unittest.TestCase):
    def test_solidworks_extensions_are_shortened(self):
        self.assertEqual(list_view.file_types(["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]), "DRW, PRT")

    def test_other_extensions_and_duplicates(self):
        self.assertEqual(list_view.file_types(["cad/a.STEP", "cad/b.STEP", "cad/c.SLDASM"]), "STEP, ASM")

    def test_empty(self):
        self.assertEqual(list_view.file_types([]), "")


class TestSortOrder(unittest.TestCase):
    def test_numbers_sort_as_numbers_and_capitals_are_ignored(self):
        values = ["b10", "B9", "a", "b2"]
        self.assertEqual([values[i] for i in list_view.sort_order(values)], ["a", "b2", "B9", "b10"])
        self.assertEqual([values[i] for i in list_view.sort_order(values, reverse=True)],
                         ["b10", "B9", "b2", "a"])

    def test_blanks_always_come_last(self):
        values = ["", "PRT", " ", "ASM, DRW"]
        self.assertEqual([values[i] for i in list_view.sort_order(values)], ["ASM, DRW", "PRT", "", " "])
        self.assertEqual([values[i] for i in list_view.sort_order(values, True)], ["PRT", "ASM, DRW", "", " "])

    def test_equal_values_keep_their_order(self):
        self.assertEqual(list_view.sort_order(["x", "x", "x"]), [0, 1, 2])
        self.assertEqual(list_view.sort_order(["x", "x", "x"], True), [0, 1, 2])

    def test_mixed_text_and_numbers_do_not_crash(self):
        self.assertEqual(len(list_view.sort_order(["10", "abc", "9", "2x", "x2"])), 5)


class TestSearchFields(unittest.TestCase):
    def test_search_matches_name_description_and_import_path(self):
        rows = [row(1, name="Front upright", description="6061 tag: suspension"),
                row(2, name="Valve body", import_path=r"D:\Old\valve_v3.SLDPRT")]
        def found(text):
            return [str(r.pn) for r in list_view.filter_rows(rows, text, "All")]
        self.assertEqual(found("upright"), ["HCR-00001-001"])
        self.assertEqual(found("SUSPENSION"), ["HCR-00001-001"])
        self.assertEqual(found("valve_v3"), ["HCR-00002-001"])
        self.assertEqual(found("00002"), ["HCR-00002-001"])
        self.assertEqual(found("nothing"), [])


class TestShiftRange(unittest.TestCase):
    def test_range_either_direction(self):
        shown = ["a", "b", "c", "d"]
        self.assertEqual(list_view.range_between(shown, "b", "d"), ["b", "c", "d"])
        self.assertEqual(list_view.range_between(shown, "d", "b"), ["b", "c", "d"])

    def test_no_anchor_is_just_the_row(self):
        self.assertEqual(list_view.range_between(["a", "b"], None, "b"), ["b"])
        self.assertEqual(list_view.range_between(["a", "b"], "gone", "b"), ["b"])

    def test_shift_held(self):
        from types import SimpleNamespace
        self.assertTrue(list_view.shift_held(SimpleNamespace(state=0x1)))
        self.assertTrue(list_view.shift_held(SimpleNamespace(state=0x9)))
        self.assertFalse(list_view.shift_held(SimpleNamespace(state=0x8)))


if __name__ == "__main__":
    unittest.main()
