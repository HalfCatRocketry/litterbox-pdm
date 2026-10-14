"""Tests for gui/logic/icon_files.py."""

import tempfile
import unittest
from pathlib import Path
from litterbox.gui.logic import icon_files


class TestIcon(unittest.TestCase):
    def test_names(self):
        self.assertEqual(icon_files.icon_filename(), "litterbox_icon_white.ico")
        self.assertEqual(icon_files.icon_filename("black"), "litterbox_icon_black.ico")
        self.assertEqual(icon_files.icon_filename(" Black "), "litterbox_icon_black.ico")
        for odd in ("", None, "purple", 5):
            self.assertEqual(icon_files.icon_filename(odd), "litterbox_icon_white.ico")

    def test_find_icon_prefers_the_choice_then_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertIsNone(icon_files.find_icon(folder))
            self.assertIsNone(icon_files.find_icon(folder / "missing"))
            (folder / "litterbox_icon_black.ico").write_bytes(b"x")
            self.assertEqual(icon_files.find_icon(folder).name, "litterbox_icon_black.ico")      # only one exists
            (folder / "litterbox_icon_white.ico").write_bytes(b"x")
            self.assertEqual(icon_files.find_icon(folder).name, "litterbox_icon_white.ico")      # default is white
            self.assertEqual(icon_files.find_icon(folder, "black").name, "litterbox_icon_black.ico")
            (folder / "litterbox_icon_white.ico").unlink()
            self.assertEqual(icon_files.find_icon(folder, "white").name, "litterbox_icon_black.ico")


if __name__ == "__main__":
    unittest.main()
