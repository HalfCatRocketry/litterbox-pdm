"""Tests for gui/logic/number_input.py: numbers typed into dialogs."""

import unittest
from litterbox.gui.logic import number_input
from litterbox.core.part_number import PN


class TestTypedNumbers(unittest.TestCase):
    def test_typed_numbers_must_be_written_in_full(self):
        self.assertEqual(number_input.parse_typed_number("00002", "part number", 5), 2)
        self.assertEqual(number_input.parse_typed_number(" 10001 ", "part number", 5), 10001)
        self.assertEqual(number_input.parse_typed_number("001", "variant number", 3), 1)
        for blank in ("", "  ", None):
            self.assertIsNone(number_input.parse_typed_number(blank, "part number", 5))
        for bad in ("2", "0002", "000002", "abcde", "1.234", "-0002", "\u00b2\u00b2\u00b2\u00b2\u00b2", "00000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                number_input.parse_typed_number(bad, "part number", 5)
        with self.assertRaises(ValueError) as ctx:
            number_input.parse_typed_number("2", "part number", 5)
        self.assertIn("exactly 5 digits", str(ctx.exception))
        self.assertIn("00001", str(ctx.exception))
        with self.assertRaises(ValueError):
            number_input.parse_typed_number("1", "variant number", 3)
        self.assertEqual(number_input.parse_typed_number("000042", "part number", 6), 42)    # other digit counts

    def test_digit_count_boxes(self):
        self.assertEqual(number_input.parse_digit_count(" 5 ", "part number digits", 1, 9), 5)
        for bad in ("", "0", "10", "x", "-1", "2.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                number_input.parse_digit_count(bad, "part number digits", 1, 9)

    def test_in_use_text_names_the_part(self):
        from litterbox.parts.number_suggestions import NumberCheck
        self.assertEqual(number_input.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "Front upright", "in_work")),
                         "Front upright")
        self.assertEqual(number_input.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "Old bracket", "void")),
                         "Old bracket (void)")
        self.assertEqual(number_input.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "", "")), "(no name)")


class TestNewNumberHelpers(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(number_input.parse_number(" 42 ", "part number"), 42)
        self.assertEqual(number_input.parse_number("007", "variant number", maximum=999), 7)
        for bad in ("", "  ", "abc", "4.5", "-3", "\u00b2", "0"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                number_input.parse_number(bad, "part number")
        with self.assertRaises(ValueError) as ctx:
            number_input.parse_number("1000", "variant number", maximum=999)
        self.assertIn("999", str(ctx.exception))



if __name__ == "__main__":
    unittest.main()
