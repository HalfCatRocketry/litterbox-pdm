"""Tests for gui/widgets/table_sorting.py. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, SortableFakeTree


class TableSorting(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.tree = SortableFakeTree(["pn", "files"])
        for iid, files in (("A", "PRT"), ("B", "ASM, DRW"), ("C", ""), ("D", "ASM")):
            self.tree.insert("", "end", iid=iid, values=[iid, files])
        self.sorter = self.gui.table_sorting.TableSorter(self.tree, [("pn", "Part number"), ("files", "Files")])

    def test_clicking_a_heading_sorts_then_reverses_with_an_arrow(self):
        self.tree.commands["files"]()
        self.assertEqual(list(self.tree.rows), ["D", "B", "A", "C"])        # ASM, ASM+DRW, PRT, blank last
        self.assertEqual(self.tree.titles["files"], "Files ▲")
        self.assertEqual(self.tree.titles["pn"], "Part number")
        self.tree.commands["files"]()
        self.assertEqual(list(self.tree.rows), ["A", "B", "D", "C"])
        self.assertEqual(self.tree.titles["files"], "Files ▼")
        self.tree.commands["pn"]()                                          # a new column starts ascending
        self.assertEqual(list(self.tree.rows), ["A", "B", "C", "D"])
        self.assertEqual((self.tree.titles["pn"], self.tree.titles["files"]), ("Part number ▲", "Files"))

    def test_the_sort_is_kept_when_the_table_is_redrawn(self):
        self.tree.commands["files"]()
        self.tree.delete(*self.tree.get_children())
        for iid, files in (("A", "PRT"), ("B", "ASM, DRW"), ("E", "ASM")):
            self.tree.insert("", "end", iid=iid, values=[iid, files])
        self.sorter.apply()
        self.assertEqual(list(self.tree.rows), ["E", "B", "A"])


if __name__ == "__main__":
    unittest.main()
