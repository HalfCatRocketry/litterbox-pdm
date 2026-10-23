"""Tests for gui/logic/search_text.py, list_columns.py and text_fit.py: the search box, the list's columns, and
cutting long text with an ellipsis."""

import unittest

from litterbox.core.part_number import PN
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import search_text
from litterbox.gui.logic import text_fit
from litterbox.parts.part_status import PartStatus


class SearchText(unittest.TestCase):
    def found(self, text, values):
        match = search_text.matcher(text)
        return [value for value in values if match(value)]

    def test_plain_text_is_contains_ignoring_capitals(self):
        self.assertEqual(self.found("BRACKET", ["Motor bracket", "Bracketry", "Plate"]), ["Motor bracket", "Bracketry"])

    def test_star_matches_the_whole_value(self):
        names = ["Test Part", "TestPart", "Te rt", "My Test Part", "Test Parts", "test part"]
        self.assertEqual(self.found("Te*rt", names), ["Test Part", "TestPart", "Te rt", "test part"])

    def test_stars_at_both_ends_mean_contains(self):
        self.assertEqual(self.found("*test*", ["My Test Part", "Plate"]), ["My Test Part"])

    def test_question_mark_is_one_character(self):
        self.assertEqual(self.found("HCR-0000?-001", ["HCR-00001-001", "HCR-00012-001", "HCR-0000-001"]),
                         ["HCR-00001-001"])

    def test_other_regex_characters_are_plain(self):
        self.assertEqual(self.found("a+b*", ["a+b plate", "aab"]), ["a+b plate"])
        self.assertEqual(self.found("(1)", ["Part (1)", "Part 1"]), ["Part (1)"])

    def test_empty_matches_everything_and_blank_values_are_safe(self):
        self.assertEqual(self.found("  ", ["a", ""]), ["a", ""])
        self.assertEqual(self.found("*", ["", None]), ["", None])
        self.assertEqual(self.found("x", [None]), [])


def part(**fields):
    defaults = dict(pn=PN("HCR", 7, 1), name="Bracket", record_status="in_work", state="Checked out by Bea",
                    kind="theirs", locked_by="Bea", files=["cad/HCR-00007-001_A.SLDPRT"], description="Motor mount",
                    revision="B", released_revision="A")
    defaults.update(fields)
    return PartStatus(**defaults)


class Columns(unittest.TestCase):
    def test_default_columns(self):
        self.assertEqual(list_columns.shown_keys(None), ["pn", "rev", "name", "description", "files", "kind"])
        self.assertEqual(list_columns.shown_keys("junk"), list_columns.shown_keys(None))

    def test_saved_columns_keep_the_list_order_and_always_the_part_number(self):
        self.assertEqual(list_columns.shown_keys(["files", "name", "nonsense"]), ["pn", "name", "files"])
        self.assertEqual(list_columns.shown_keys(["pn"]), ["pn"])

    def test_toggling(self):
        keys = list_columns.shown_keys(None)
        self.assertEqual(list_columns.toggled(keys, "cots"),
                         ["pn", "rev", "name", "description", "files", "kind", "cots"])
        self.assertEqual(list_columns.toggled(keys, "name"), ["pn", "rev", "description", "files", "kind"])
        self.assertEqual(list_columns.toggled(keys, "pn"), keys)

    def test_what_each_column_shows(self):
        row = part()
        texts = {column.key: column.text(row) for column in list_columns.COLUMNS}
        self.assertEqual(texts["pn"], "00007-001")
        self.assertEqual(texts["files"], "PRT")
        self.assertEqual(texts["locked_by"], "Bea")
        self.assertEqual(texts["released"], "A")
        self.assertEqual(list_columns.BY_KEY["pn"].search_values(row), ("00007-001", "HCR-00007-001"))
        self.assertEqual(list_columns.BY_KEY["locked_by"].text(part(kind="ok")), "")

    def test_search_choices(self):
        self.assertEqual(list_columns.search_choices(["pn", "name"]), ["All columns", "Part number", "Name"])
        self.assertEqual(list_columns.search_keys("Name"), ["name"])
        self.assertEqual(list_columns.search_keys("All columns"), [c.key for c in list_columns.COLUMNS])

    def test_search_in_one_column(self):
        row = part()
        values = list_columns.search_values(row, list_columns.search_keys("Description"))
        self.assertEqual(values, ["Motor mount"])
        self.assertIn("HCR-00007-001", list_columns.search_values(row, list_columns.search_keys("All columns")))


class TextFit(unittest.TestCase):
    measure = staticmethod(len)                         # one pixel per character

    def test_short_text_is_unchanged(self):
        self.assertEqual(text_fit.fit("Bracket", 20, self.measure), "Bracket")

    def test_long_text_gets_an_ellipsis_and_fits(self):
        fitted = text_fit.fit("Motor mounting bracket", 10, self.measure)
        self.assertEqual(fitted, "Motor mou…")
        self.assertLessEqual(self.measure(fitted), 10)

    def test_no_trailing_space_before_the_ellipsis(self):
        self.assertEqual(text_fit.fit("Motor mounting", 7, self.measure), "Motor…")

    def test_lines_are_joined(self):
        self.assertEqual(text_fit.fit("two\nlines", 50, self.measure), "two lines")

    def test_too_narrow(self):
        self.assertEqual(text_fit.fit("Bracket", 1, self.measure), "…")
        self.assertEqual(text_fit.fit("Bracket", 0, self.measure), "Bracket")
        self.assertEqual(text_fit.fit("", 5, self.measure), "")


if __name__ == "__main__":
    unittest.main()
