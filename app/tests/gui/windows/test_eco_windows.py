"""Tests for the ECO parts of the windows: the Workflow window's parts list and ECO form, Add Parts, a part's
Details tab, and the ECOs windows. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these
check the wiring, not the look. Please also try the real window."""

import unittest
from types import SimpleNamespace
from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes, replace
from litterbox.change_orders import eco_model
from litterbox.core.part_number import PN
from litterbox.records import record_model
from litterbox.team import team_model
from litterbox.workflows import workflow_templates

P1, P2, P3 = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)
AT = "2026-10-11T09:30:00Z"


class Setup(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)


class RequestWindow(Setup):
    def setUp(self):
        super().setUp()
        rows = [workflow_templates.Row(["Quality"])]
        self.templates = {"T1": workflow_templates.Template("release", "T1", rows, require_eco=True),
                          "T2": workflow_templates.Template("release", "T2", rows)}
        directory = team_model.Directory(
            [team_model.Person("alex", "Alex", "", ["Alex"], "owner", ["Responsible Engineer"]),
             team_model.Person("bea", "Bea", "", ["Bea"], "member", ["Quality"])], ["Responsible Engineer", "Quality"])
        self.offered = [SimpleNamespace(pn=P2, name="Arm"), SimpleNamespace(pn=P3, name="Plate")]
        self.asked_for = []
        self.dialog = self.gui.request_dialog.WorkflowRequestDialog(
            FakeParent(), "release", [(P1, "Bracket")], self.templates, directory, "alex",
            lambda current: self.asked_for.append(list(current)) or list(self.offered))
        self.dialog.reason_var.set("")                  # real text boxes start empty, the stand-ins at None
        self.dialog.eco_name_var.set("")
        self.dialog.eco_description = SimpleNamespace(get=lambda start, end: "  Wall from 2 to 3 mm\n")
        self.problems = []
        self.dialog.problem = SimpleNamespace(configure=lambda text: self.problems.append(text))

    def pick(self, answer):
        replace(self, self.gui.part_picker_dialog, "PartPickerDialog",
                lambda parent, rows, label: SimpleNamespace(show=lambda: answer))

    def test_parts_are_added_and_removed(self):
        self.assertEqual(list(self.dialog.parts_tree.rows), ["HCR-00001-001"])
        self.pick([P2, P3])
        self.dialog._add_parts()
        self.assertEqual(self.asked_for, [[P1]])
        self.assertEqual(self.dialog.parts, [(P1, "Bracket"), (P2, "Arm"), (P3, "Plate")])
        self.assertEqual(list(self.dialog.parts_tree.rows), ["HCR-00001-001", "HCR-00002-001", "HCR-00003-001"])
        self.dialog.parts_tree.selection_set("HCR-00001-001", "HCR-00003-001")
        self.dialog._remove_parts()
        self.assertEqual(self.dialog.parts, [(P2, "Arm")])
        self.dialog.parts_tree.selection_set()
        self.dialog._remove_parts()
        self.assertIn("Select the parts", self.problems[-1])

    def test_cancelling_add_parts_changes_nothing(self):
        self.pick(None)
        self.dialog._add_parts()
        self.assertEqual(self.dialog.parts, [(P1, "Bracket")])

    def test_a_workflow_that_requires_an_eco_needs_its_name(self):
        self.dialog._submit()
        self.assertEqual(self.problems[-1], "The ECO needs a name.")
        self.assertIsNone(self.dialog.result)
        self.dialog.eco_name_var.set("  Thicker   wall ")
        self.dialog._submit()
        self.assertEqual(self.dialog.result["eco"], {"name": "Thicker wall", "description": "Wall from 2 to 3 mm"})
        self.assertEqual(self.dialog.result["parts"], [P1])
        question = [c for c in self.box.calls if c[0] == "askokcancel"][-1][1][1]
        self.assertIn("ECO) will be made: Thicker wall", question)

    def test_a_workflow_without_the_box_has_no_eco(self):
        self.dialog.template_var.set("T2")
        self.dialog._rebuild()
        self.dialog._submit()
        self.assertIsNone(self.dialog.result["eco"])

    def test_at_least_one_part_is_needed(self):
        self.dialog.template_var.set("T2")
        self.dialog.parts = []
        self.dialog._submit()
        self.assertIn("at least one part", self.problems[-1])
        self.assertIsNone(self.dialog.result)


class PartPicker(Setup):
    def test_search_and_pick(self):
        rows = [SimpleNamespace(pn=P2, name="Arm", kind="ok", state="Available", description="", import_path=""),
                SimpleNamespace(pn=P3, name="Plate", kind="ok", state="Available", description="", import_path="")]
        picker = self.gui.part_picker_dialog.PartPickerDialog(FakeParent(), rows, "Release")
        self.assertEqual(list(picker.tree.rows), ["HCR-00002-001", "HCR-00003-001"])
        picker.search_var.set("plate")                  # typing filters the list
        self.assertEqual(list(picker.tree.rows), ["HCR-00003-001"])
        picker._add()
        self.assertIsNone(picker.result)                # nothing selected yet
        picker.tree.selection_set("HCR-00003-001")
        picker._add()
        self.assertEqual(picker.result, [P3])


class DetailsTab(Setup):
    def setUp(self):
        super().setUp()
        record = record_model.Record(P1, "Bracket", "Alex Smith", AT, revision="B", released_revision="A")
        record.history = [{"event": "released", "by": "Bea", "at": AT, "revision": "A", "eco": "ECO-0001"}]
        record.approvals = [{"action": "release", "revision": "A", "eco": "ECO-0001", "signoffs": []}]
        self.viewed = []
        self.window = self.gui.history_window.HistoryWindow(
            FakeParent(), record, {"A": ["cad/HCR-00001-001_A.SLDPRT"]}, on_open=lambda *a: None,
            on_view_eco=self.viewed.append)

    def test_the_latest_revision_is_shown_first_and_another_can_be_picked(self):
        self.assertEqual(self.window.rev_var.get(), "B")
        self.assertEqual(dict(self.window.shown)["ECO"], "None")
        self.window._view_eco()
        self.assertEqual(self.viewed, [])
        self.window.rev_var.set("A")
        self.window._show_revision()
        self.assertTrue(dict(self.window.shown)["ECO"].startswith("ECO-0001"))
        self.window._view_eco()
        self.assertEqual(self.viewed, ["ECO-0001"])
        self.assertEqual(len(self.window.tree.rows), 1)          # the History tab is still there


class EcoWindows(Setup):
    def ecos(self):
        return [eco_model.Eco("ECO-0002", "Supplier", "Cheaper steel", eco_model.RELEASED, "release", "T1", "r2",
                              [{"pn": "HCR-00002-001", "revision": "A"}], "Alex", AT),
                eco_model.Eco("ECO-0001", "Bracket", "", eco_model.OPEN, "release", "T1", "r1", [], "Alex", AT)]

    def test_the_list_searches_and_views(self):
        viewed = []
        window = self.gui.eco_list_window.EcoListWindow(FakeParent(), self.ecos(), {}, viewed.append)
        self.assertEqual(list(window.tree.rows), ["ECO-0002", "ECO-0001"])
        window.search_var.set("steel")
        self.assertEqual(list(window.tree.rows), ["ECO-0002"])
        window.search_var.set("")
        window.status_var.set("Open")
        window._fill()
        self.assertEqual(list(window.tree.rows), ["ECO-0001"])
        window._view()
        self.assertEqual(viewed, [])
        window.tree.selection_set("ECO-0001")
        window._view()
        self.assertEqual([e.number for e in viewed], ["ECO-0001"])

    def test_one_eco_window_lists_its_parts(self):
        window = self.gui.eco_view_window.EcoViewWindow(FakeParent(), self.ecos()[0])
        self.assertEqual([r["values"] for r in window.parts.rows.values()], [["HCR-00002-001", "A"]])

    def test_the_main_window_opens_them(self):
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: "C:/vault"
        opened = []
        replace(self, self.gui.eco_store, "load_all", lambda repo: (self.ecos(), {}))
        replace(self, self.gui.eco_list_window, "EcoListWindow",
                lambda parent, ecos, problems, on_view: opened.append(("list", [e.number for e in ecos])))
        replace(self, self.gui.eco_view_window, "EcoViewWindow", lambda parent, eco: opened.append(("one", eco.number)))
        app.show_ecos()
        replace(self, self.gui.eco_store, "load", lambda repo, number: self.ecos()[1])
        app.view_eco("ECO-0001")
        self.assertEqual(opened, [("list", ["ECO-0002", "ECO-0001"]), ("one", "ECO-0001")])

        def missing(repo, number):
            raise eco_model.EcoError("There is no ECO-0009 in your copy of the vault. Try Get Latest.")
        replace(self, self.gui.eco_store, "load", missing)
        app.view_eco("ECO-0009")
        self.assertEqual([c[0] for c in self.box.calls], ["showerror"])
