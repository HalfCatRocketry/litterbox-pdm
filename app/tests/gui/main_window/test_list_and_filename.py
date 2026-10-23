"""Tests for the parts list and the file name window. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import types
import unittest
from tests.support.gui_fakes import FakeBox, fake_jobs, load_gui_with_fakes, FakeParent, SortableFakeTree


class ListAndFilenameWiring(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.parts.part_status import PartStatus
        from litterbox.core.part_number import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Bracket", "in_work", "Available (Rev A released)", "ok",
                              files=["cad/HCR-00007-001_B.SLDPRT"], revision="B", released_revision="A",
                              revisions={"B": ["cad/HCR-00007-001_B.SLDPRT"]})

    KEYS = ["pn", "name", "description", "rev", "files", "cots", "state", "locked_by", "released", "import_path"]

    def app(self, rows, view="All", search=""):
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.jobs = fake_jobs()
        app.rows = rows
        app.search = types.SimpleNamespace(get=lambda: search)
        app.view = types.SimpleNamespace(get=lambda: view)
        app.ticked = set()
        app.icons = self.gui.icon_images.IconImages(None)
        app.tree = SortableFakeTree(self.KEYS)
        app.sorter = self.gui.table_sorting.TableSorter(app.tree, [])
        return app

    def test_the_list_shows_the_short_part_number_and_the_revision(self):
        app = self.app([self.row])
        self.assertEqual(app._render(), 1)
        self.assertEqual(app.tree.rows["HCR-00007-001"]["values"],
                         ["00007-001", "B", "Bracket", "", "", "PRT", "CAD", "", "Available (Rev A released)", "", "A", "",
                          ""])
        self.assertIn("image", app.tree.rows["HCR-00007-001"])          # the tick box and status icon

    def test_long_names_are_cut_to_the_column_width(self):
        from litterbox.parts.part_status import PartStatus
        long = PartStatus(self.pn, "A very long name for a small bracket", "in_work", "Available", "ok")
        app = self.app([long])
        app.tree.widths["name"] = 14 + 7 * 10                             # room for ten characters (see FakeFont)
        app._render()
        self.assertEqual(app.tree.rows["HCR-00007-001"]["values"][2], "A very lo\u2026")      # ten characters
        self.assertEqual(app._cell_tooltip("HCR-00007-001", "name"), "A very long name for a small bracket")
        self.assertEqual(app._cell_tooltip("HCR-00007-001", "rev"), "")

    def test_the_status_icon_tooltip_says_what_it_means(self):
        app = self.app([self.row])
        app._render()
        self.assertEqual(app._cell_tooltip("HCR-00007-001", "#0"), "Checked in: Available (Rev A released)")

    def test_search_in_one_column_and_with_wildcards(self):
        for choice, text, found in (("All columns", "brack", 1), ("Description", "brack", 0), ("Name", "B*t", 1),
                                    ("Name", "B*", 1), ("Name", "*rack", 0)):
            app = self.app([self.row], search=text)
            app.search_in = types.SimpleNamespace(get=lambda choice=choice: choice)
            self.assertEqual(app._render(), found, (choice, text))

    def test_a_voided_part_that_is_hidden_loses_its_tick(self):
        from litterbox.parts.part_status import PartStatus
        voided = PartStatus(self.pn, "Bracket", "void", "Void", "void")
        for view, expected in (("All", set()), ("Void", {"HCR-00007-001"})):
            app = self.app([voided], view=view)
            app.ticked = {"HCR-00007-001"}
            app._render()
            self.assertEqual(app.ticked, expected)

    def test_search_finds_a_part_by_the_short_or_the_full_number(self):
        for text in ("00007-001", "HCR-00007-001"):
            self.assertEqual(len(self.gui.list_view.filter_rows([self.row], text)), 1)

    def test_new_part_shows_the_filename_to_save_as_and_copies_it(self):
        dialog = self.gui.filename_dialog.FilenameDialog(FakeParent(), self.pn)
        self.assertEqual(dialog.stem, "HCR-00007-001_A")
        copied = []
        dialog.clipboard_clear = lambda: copied.append("cleared")
        dialog.clipboard_append = copied.append
        dialog._copy()
        self.assertEqual(copied, ["cleared", "HCR-00007-001_A"])


if __name__ == "__main__":
    unittest.main()
