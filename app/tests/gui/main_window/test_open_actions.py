"""Tests for Open, Open Drawing, Open PDF, a document's Details window and the reference review. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from pathlib import Path
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace


class OpenWiring(unittest.TestCase):
    """The Open and Open Drawing buttons: which file opens, and when the user is asked which revision."""
    A = ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"]
    B = ["cad/HCR-00007-001_B.SLDPRT", "cad/HCR-00007-001_B.SLDDRW"]

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        from litterbox.parts.part_status import PartStatus
        from litterbox.core.part_number import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=list(self.B), revision="B",
                              released_revision="A", revisions={"A": self.A, "B": self.B})
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {self.pn: self.row}
        app._selected_pns = lambda action=None: [self.pn]
        app.repo = lambda: "C:/vault"
        app.settings = {"open_with": {".pdf": "x"}}
        self.said = []
        app._say = lambda text, tone="normal": self.said.append(text)
        self.app = app
        self.opened, self.asked = [], []
        original_open = self.gui.opener.open_path
        self.addCleanup(setattr, self.gui.opener, "open_path", original_open)     # don't leak into other tests
        self.gui.opener.open_path = lambda path, settings=None: self.opened.append((Path(path).name, settings))

        outer = self

        class FakePicker:
            answer = "A"

            def __init__(self, parent, pn, choices, title="Open"):
                outer.asked.append(([label for label, _rev in choices], title))

            def show(self):
                return FakePicker.answer
        self.picker = FakePicker
        self.gui.revision_picker.RevisionPickerDialog = FakePicker

    def test_a_released_and_a_working_revision_ask_which_to_open(self):
        self.app.open_part()
        self.assertEqual(self.asked, [(["Rev B (working)", "Rev A (released)"], "Open")])
        self.assertEqual(self.opened, [("HCR-00007-001_A.SLDPRT", {".pdf": "x"})])      # answered A

    def test_cancelling_the_question_opens_nothing(self):
        self.picker.answer = None
        self.app.open_part()
        self.assertEqual(self.opened, [])

    def test_open_drawing_asks_too_when_both_revisions_have_a_drawing(self):
        self.picker.answer = "B"
        self.app.open_part(drawing=True)
        self.assertEqual(self.asked[0][1], "Open drawing of")
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDDRW")

    def test_no_question_when_there_is_only_one_revision_to_open(self):
        self.row.released_revision = ""
        self.row.revisions = {"B": self.B}
        self.app.open_part()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")

    def test_open_drawing_with_a_drawing_in_one_revision_does_not_ask(self):
        self.row.revisions = {"A": self.A, "B": ["cad/HCR-00007-001_B.SLDPRT"]}
        self.app.open_part(drawing=True)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_A.SLDDRW")

    # -- out-of-date parts offered when an assembly in work is opened -------------------------
    def _stale(self, replaceable=True):
        from types import SimpleNamespace as S
        from litterbox.core.part_number import PN
        return S(child=PN("HCR", 3, 1), child_revision="A", latest_released="B", replaceable=replaceable)

    def test_opening_an_assembly_with_out_of_date_parts_offers_a_review(self):
        replace(self, self.gui.reference_queries, "uses", lambda repo, pn, rev: [self._stale()])
        asked, loaded = [], []
        self.box.askyesno = lambda title, text: asked.append((title, text)) or True
        self.gui.messagebox.askyesno = self.box.askyesno
        self.app._load_references = lambda pn: loaded.append(pn)
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(loaded, [self.pn])
        self.assertEqual(self.opened, [])
        self.assertIn("newer released revision", asked[0][1])

    def test_declining_the_review_opens_the_file_anyway(self):
        replace(self, self.gui.reference_queries, "uses", lambda repo, pn, rev: [self._stale()])
        self.gui.messagebox.askyesno = lambda title, text: False
        self.app._load_references = lambda pn: self.fail("should not review")
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")

    def test_no_offer_for_the_released_revision_or_when_nothing_can_change(self):
        replace(self, self.gui.reference_queries, "uses", lambda repo, pn, rev: [self._stale()])
        self.gui.messagebox.askyesno = lambda *a: self.fail("should not ask")
        self.picker.answer = "A"                        # the released revision: frozen, nothing to replace
        self.app.open_part()
        self.assertEqual(len(self.opened), 1)
        replace(self, self.gui.reference_queries, "uses", lambda repo, pn, rev: [self._stale(False)])
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(len(self.opened), 2)

    def test_open_also_offers_revisions_released_before(self):
        self.row.revision, self.row.released_revision, self.row.released_revisions = "C", "B", ("A", "B")
        self.row.revisions = {"A": self.A, "B": self.B, "C": ["cad/HCR-00007-001_C.SLDPRT"]}
        self.app.open_part()
        self.assertEqual(self.asked[0][0], ["Rev C (working)", "Rev B (released)", "Rev A (previously released)"])
        self.assertEqual(self.opened, [("HCR-00007-001_A.SLDPRT", {".pdf": "x"})])      # answered A

    def test_the_pop_out_details_window_reads_its_own_parts_tabs(self):
        from litterbox.records import record_model
        record = record_model.Record(self.pn, "Part", "Alex", "2026-10-01T10:00:00Z", revision="B",
                                     released_revision="A")
        replace(self, self.gui.record_store, "load", lambda repo, pn: record)
        windows, read, exported = [], [], []
        real = self.gui.history_window.HistoryWindow
        replace(self, self.gui.history_window, "HistoryWindow",
                lambda *a, **k: windows.append(real(*a, **k)) or windows[-1])
        self.app._read_references_into = lambda view, pn, wanted: read.append(("references", pn))
        self.app._read_bom_into = lambda view, pn, wanted: read.append(("bom", pn))
        self.app.export_bom = lambda rev, mode, pn=None: exported.append((rev, pn))
        self.app.show_history()
        view = windows[0].view
        self.assertIn("Where used", view.reference_trees)
        for tab in ("Uses", "Where used", "BOM", "Uses"):
            view.on_tab(tab)
        self.assertEqual(read, [("references", self.pn), ("bom", self.pn)])        # each read once
        view.on_export_bom("A", "flat")
        self.assertEqual(exported, [("A", self.pn)])

    def test_history_window_can_open_a_chosen_revision(self):
        self.app._open_revision(self.pn, "A", False)
        self.app._open_revision(self.pn, "B", True)
        self.assertEqual([name for name, _s in self.opened], ["HCR-00007-001_A.SLDPRT", "HCR-00007-001_B.SLDDRW"])
        self.app._open_revision(self.pn, "C", False)
        self.assertIn("no file", self.said[-1])


class OpenDownloadsFirst(unittest.TestCase):
    """Download on demand: a part (or an assembly's parts) that isn't downloaded is fetched in the background,
    and opened once it is there."""
    A, B = OpenWiring.A, OpenWiring.B

    def setUp(self):
        OpenWiring.setUp(self)                              # the same window, without OpenWiring's own tests
        self.tasks = []
        self.app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, done, on_success, kw))
        self.needed = ["cad/HCR-00007-001_B.SLDPRT"]
        replace(self, self.gui.downloads, "files_to_open", lambda repo, pn, rev: list(self.needed))
        replace(self, self.gui.lfs_download, "stubs", lambda repo, files: [f for f in files if f in self.needed])
        self.fetched = []
        replace(self, self.gui.downloads, "download_for_open", lambda repo, pn, rev: self.fetched.append(rev) or ["x"])

    def test_a_part_that_is_not_downloaded_is_fetched_then_opened(self):
        self.app._open_revision(self.pn, "B")
        self.assertEqual(self.opened, [])                                   # not yet: it is being downloaded
        work, done, on_success, kw = self.tasks[0]
        self.assertEqual(kw["label"], "Downloading 1 file for 00007-001")
        self.assertEqual(kw["parts"], [self.pn])
        on_success(work())                                                  # the job finishes
        self.assertEqual(self.fetched, ["B"])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")

    def test_a_downloaded_part_opens_at_once(self):
        self.needed = []
        self.app._open_revision(self.pn, "B")
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")



class OpenPdfWiring(unittest.TestCase):
    """Open PDF: every revision with a PDF is offered, and only the PDF is downloaded first."""
    A, B = OpenWiring.A, OpenWiring.B

    def setUp(self):
        OpenWiring.setUp(self)
        self.app._plan = lambda action: self.gui.action_rules.plan_action(action, [self.pn], self.app.rows_by_pn)
        self.row.revisions = {"A": self.A + ["cad/HCR-00007-001_A.PDF"], "B": self.B + ["cad/HCR-00007-001_B.PDF"]}
        self.tasks = []
        self.app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, on_success, kw))
        self.stubs = []
        replace(self, self.gui.lfs_download, "is_stub", lambda repo, path: path in self.stubs)

    def test_the_revisions_with_a_pdf_are_offered_newest_first(self):
        self.app.open_pdf()
        self.assertEqual(self.asked, [(["Rev B (working)", "Rev A (released)"], "Open PDF of")])
        self.assertEqual(self.opened, [("HCR-00007-001_A.PDF", {".pdf": "x"})])           # answered A

    def test_one_pdf_opens_without_asking_and_none_says_why(self):
        self.row.revisions = {"A": self.A + ["cad/HCR-00007-001_A.PDF"], "B": self.B}
        self.app.open_pdf()
        self.assertEqual((self.asked, self.opened[0][0]), ([], "HCR-00007-001_A.PDF"))
        self.row.revisions = {"A": self.A, "B": self.B}
        self.app.open_pdf()
        self.assertIn("Generate STEP/PDF", self.said[-1])

    def test_a_pdf_that_is_not_downloaded_is_fetched_alone(self):
        self.stubs = ["cad/HCR-00007-001_A.PDF"]
        fetched = []
        replace(self, self.gui.downloads, "download_files", lambda repo, rels, label: fetched.append(rels) or rels)
        self.app.open_pdf()
        work, on_success, kw = self.tasks[0]
        on_success(work())
        self.assertEqual(fetched, [["cad/HCR-00007-001_A.PDF"]])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_A.PDF")

    def test_open_pdf_is_in_the_part_menu_and_the_right_click_menu_builds(self):
        self.assertIn(("Open PDF", "open_pdf"), self.gui.menus.PART_MENU)
        filled = []
        self.app.tree = self.gui.ttk.Treeview()
        self.app.tree.identify_row = lambda y: str(self.pn)
        self.app.ticked = set()
        self.app._set_ticks = lambda iids, on: None
        self.app._ticked_pns = lambda: [self.pn]
        self.app._lifecycle_entries = lambda: ()
        self.app._fill_actions = lambda menu, entries: filled.extend(entries)
        self.app._on_right_click(type("Event", (), {"y": 1, "x_root": 0, "y_root": 0})())
        self.assertIn(("Open PDF", "open_pdf"), filled)


class DocumentDetailsWiring(unittest.TestCase):
    """A document's Details... opens a window of its own, with the part revisions that link to it."""

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        from litterbox.core.doc_number import DocNumber
        from litterbox.core.part_number import PN
        from litterbox.parts.part_status import PartStatus
        from litterbox.records import record_model
        self.number, self.part = DocNumber("PROP", 1), PN("HCR", 7, 1)
        self.record = record_model.Record(self.number, "Igniter test", "Alex", "2026-10-01T10:00:00Z")
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {self.number: PartStatus(self.number, "Igniter test", "in_work", "Available", "ok",
                                                  revisions={"A": ["documents/PROP-0001_A.pdf"]}),
                          self.part: PartStatus(self.part, "Igniter", "in_work", "Available", "ok")}
        app._selected_pns = lambda action=None: [self.number]
        app.repo = lambda: "C:/vault"
        app._say = lambda text, tone="normal": None
        self.tasks, self.acted = [], []
        app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, on_success))
        app.act_on = lambda numbers, method, *args: self.acted.append((numbers, method))
        self.app = app
        replace(self, self.gui.record_store, "load", lambda repo, pn: self.record)
        replace(self, self.gui.doc_types, "load", lambda repo: [])
        replace(self, self.gui.doc_links, "where_linked", lambda repo, number: [(self.part, "A")])

    def test_a_document_gets_its_own_window_not_the_parts_pop_out(self):
        windows, links = [], []
        real = self.gui.document_window.DocumentWindow
        replace(self, self.gui.document_window, "DocumentWindow",
                lambda *a, **k: windows.append(real(*a, **k)) or windows[-1])
        replace(self, self.gui.history_window, "HistoryWindow", lambda *a, **k: self.fail("the parts' pop-out"))
        self.app.show_history()
        window = windows[0]
        window.show_links = lambda found, rows, message="": links.append(found)
        work, on_success = self.tasks[0]
        on_success(work())
        self.assertEqual(links, [[(self.part, "A")]])
        window.links = {"x": self.part}
        window.linked_tree.selection = lambda: ("x",)
        window._show_part()
        self.assertEqual(self.acted, [([self.part], self.app.show_history)])


if __name__ == "__main__":
    unittest.main()
