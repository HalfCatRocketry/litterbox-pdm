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

    def test_the_list_shows_the_short_part_number_and_the_revision(self):
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.jobs = fake_jobs()
        app.rows = [self.row]
        app.search = types.SimpleNamespace(get=lambda: "")
        app.view = types.SimpleNamespace(get=lambda: "All")
        app.void_box = types.SimpleNamespace(get=lambda: 0)
        app.ticked = set()
        app.tree = SortableFakeTree(["tick", "pn", "name", "description", "cots", "rev", "state", "files"])
        app.sorter = self.gui.table_sorting.TableSorter(app.tree, [])
        self.assertEqual(app._render(), 1)
        self.assertEqual(app.tree.rows["HCR-00007-001"]["values"],
                         ["\u2610", "00007-001", "Bracket", "", "", "B", "Available (Rev A released)", "PRT"])

    def test_a_voided_part_that_is_hidden_loses_its_tick(self):
        from litterbox.parts.part_status import PartStatus
        voided = PartStatus(self.pn, "Bracket", "void", "Void", "void")
        for shown, expected in ((0, set()), (1, {"HCR-00007-001"})):
            app = self.gui.app.App.__new__(self.gui.app.App)
            app.jobs = fake_jobs()
            app.rows = [voided]
            app.search = types.SimpleNamespace(get=lambda: "")
            app.view = types.SimpleNamespace(get=lambda: "All")
            app.void_box = types.SimpleNamespace(get=lambda shown=shown: shown)
            app.ticked = {"HCR-00007-001"}
            app.tree = SortableFakeTree(["tick", "pn", "name", "description", "cots", "rev", "state", "files"])
            app.sorter = self.gui.table_sorting.TableSorter(app.tree, [])
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
