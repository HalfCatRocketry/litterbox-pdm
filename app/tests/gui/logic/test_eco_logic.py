"""Tests for the ECO side of the window logic: gui/logic/eco_text.py, part_details_text.py and request_parts.py,
and the Require ECO box in workflow_editor.py."""

import unittest
from types import SimpleNamespace
from litterbox.change_orders import eco_model
from litterbox.core.part_number import PN
from litterbox.gui.logic import eco_text
from litterbox.gui.logic import part_details_text
from litterbox.gui.logic import request_parts
from litterbox.gui.logic import workflow_editor
from litterbox.records import record_model
from litterbox.workflows import workflow_editing

AT = "2026-10-11T09:30:00Z"


def eco(number, name, status=eco_model.OPEN, parts=("HCR-00001-001",), **fields):
    return eco_model.Eco(number, name, fields.pop("description", ""), status, "release", "T1", "req1",
                         [{"pn": p, "revision": "A"} for p in parts], "Alex Smith", AT, **fields)


class TestEcoText(unittest.TestCase):
    def setUp(self):
        self.ecos = [eco("ECO-0003", "Thicker wall", eco_model.RELEASED, ("HCR-00001-001", "HCR-00002-001", "HCR-00009-001")),
                     eco("ECO-0002", "New supplier", eco_model.REJECTED, ("HCR-00005-001",), description="Cheaper steel"),
                     eco("ECO-0001", "First", eco_model.OPEN, ())]

    def test_the_table_lists_every_eco(self):
        rows = eco_text.eco_table(self.ecos, local=False)
        self.assertEqual([iid for iid, _v in rows], ["ECO-0003", "ECO-0002", "ECO-0001"])
        self.assertEqual(rows[0][1], ("ECO-0003", "Thicker wall", "Released", "HCR-00001-001 Rev A +2 more",
                                      "Alex Smith", "2026-10-11 09:30"))
        self.assertEqual(rows[2][1][3], "")

    def test_search_and_status_filter(self):
        def found(search="", status="All"):
            return [iid for iid, _v in eco_text.eco_table(self.ecos, search, status, local=False)]
        self.assertEqual(found("steel"), ["ECO-0002"])                 # the description
        self.assertEqual(found("00009"), ["ECO-0003"])                 # a part
        self.assertEqual(found("eco-0001"), ["ECO-0001"])
        self.assertEqual(found("alex"), ["ECO-0003", "ECO-0002", "ECO-0001"])
        self.assertEqual(found(status="Rejected"), ["ECO-0002"])
        self.assertEqual(found("first", "Released"), [])
        self.assertIn("Released", eco_text.STATUS_FILTERS)

    def test_the_note_says_what_is_shown_and_what_cannot_be_read(self):
        self.assertEqual(eco_text.table_note(1, 3, {}), "1 of 3 ECOs shown.")
        self.assertIn("Can't read: ECO-0007", eco_text.table_note(0, 1, {"ECO-0007": "bad"}))

    def test_one_ecos_details(self):
        closed = eco("ECO-0002", "New supplier", eco_model.REJECTED,
                     signoffs=[{"by": "Bea Jones", "at": AT, "comment": "No"}],
                     history=[{"event": "opened", "by": "Alex Smith", "at": AT},
                              {"event": "rejected", "by": "Bea Jones", "at": AT, "comment": "Too soft"}])
        fields = dict(eco_text.eco_fields(closed, local=False))
        self.assertEqual(fields["Status"], "Rejected")
        self.assertEqual(fields["Workflow"], "Release T1")
        self.assertEqual(fields["Rejected"], "by Bea Jones on 2026-10-11 09:30 - Too soft")
        self.assertEqual(eco_text.part_rows(closed), [("HCR-00001-001", "A")])
        self.assertEqual(eco_text.signoff_rows(closed, local=False), [("Bea Jones", "2026-10-11 09:30", "No")])
        self.assertEqual(eco_text.history_rows(closed, local=False)[1], ("2026-10-11 09:30", "Bea Jones", "Rejected: Too soft"))
        self.assertNotIn("Released", dict(eco_text.eco_fields(eco("ECO-0001", "x"), local=False)))


class TestPartDetails(unittest.TestCase):
    """A part released at A with ECO-0001, at B with no ECO, and C waiting for sign-offs with ECO-0004."""

    def setUp(self):
        record = record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex Smith", AT, description="Left side",
                                     revision="C", released_revision="B", references={"A": ["HCR-00005-001_A"]})
        record.history = [
            {"event": "released", "by": "Bea Jones", "at": AT, "revision": "A", "eco": "ECO-0001"},
            {"event": "released", "by": "Bea Jones", "at": "2026-10-12T09:30:00Z", "revision": "B", "override": True},
        ]
        record.approvals = [
            {"action": "release", "revision": "A", "template_name": "T1", "eco": "ECO-0001",
             "signoffs": [{"by": "Alex Smith"}, {"by": "Bea Jones"}], "completed_at": AT},
            {"action": "release", "revision": "B", "signoffs": [], "completed_at": AT},
        ]
        record.pending = {"id": "x", "revision": "C", "eco": "ECO-0004"}
        self.record = record
        self.revisions = {"A": ["cad/HCR-00001-001_A.SLDPRT"], "B": [], "C": ["cad/HCR-00001-001_C.SLDPRT"]}

    def details(self, rev):
        return dict(part_details_text.revision_details(self.record, rev, self.revisions, local=False))

    def test_the_newest_revision_comes_first(self):
        self.assertEqual(part_details_text.revision_choices(self.record, self.revisions), ["C", "B", "A"])

    def test_each_revision_shows_its_own_eco(self):
        self.assertEqual(part_details_text.eco_for(self.record, "A"), ("ECO-0001", "Release workflow, 2026-10-11"))
        self.assertEqual(part_details_text.eco_for(self.record, "B"), (None, ""))
        self.assertEqual(part_details_text.eco_for(self.record, "C"), ("ECO-0004", "waiting for sign-offs"))
        self.assertEqual(self.details("B")["ECO"], "None")
        self.assertTrue(self.details("A")["ECO"].startswith("ECO-0001"))

    def test_revision_dependent_details_change_with_the_revision(self):
        a, b, c = self.details("A"), self.details("B"), self.details("C")
        self.assertEqual((a["Revision"], c["Revision"]), ("Rev A", "Rev C (working)"))
        self.assertEqual(a["State"], "Released (superseded)")
        self.assertEqual(b["State"], "Released")
        self.assertEqual(a["Released"], "by Bea Jones on 2026-10-11 09:30")
        self.assertIn("Admin override", b["Released"])
        self.assertNotIn("Released", c)
        self.assertEqual((a["Workflow"], a["Signed off by"]), ("Release T1", "Alex Smith, Bea Jones"))
        self.assertEqual((a["Files"], b["Files"]), ("PRT", "No files"))
        self.assertEqual(a["Uses"], "HCR-00005-001_A")
        self.assertNotIn("Uses", b)
        for one in (a, b, c):                          # the same whatever revision is picked
            self.assertEqual((one["Part"], one["Name"], one["Description"]), ("HCR-00001-001", "Bracket", "Left side"))


class TestRequestParts(unittest.TestCase):
    def row(self, n, kind, name="Part", description=""):
        return SimpleNamespace(pn=PN("HCR", n, 1), name=name, kind=kind, description=description, import_path="")

    def test_only_parts_that_can_join_are_offered(self):
        rows = [self.row(10, "ok"), self.row(2, "ok"), self.row(3, "pending"), self.row(4, "mine"),
                self.row(5, "released"), self.row(6, "ok"), self.row(7, "ok")]
        found = request_parts.addable_rows("release", rows, current=[PN("HCR", 6, 1)], busy={"HCR-00007-001": "x"})
        self.assertEqual([str(r.pn) for r in found], ["HCR-00002-001", "HCR-00010-001"])
        self.assertEqual([str(r.pn) for r in request_parts.addable_rows("reopen", rows)], ["HCR-00005-001"])

    def test_search(self):
        rows = [self.row(1, "ok", "Bracket"), self.row(2, "ok", "Arm", "steel arm"), self.row(3, "void", "Old")]
        self.assertEqual(len(request_parts.search(rows, "")), 3)
        self.assertEqual([r.name for r in request_parts.search(rows, "STEEL")], ["Arm"])
        self.assertEqual([r.name for r in request_parts.search(rows, "00001")], ["Bracket"])


class TestRequireEcoBox(unittest.TestCase):
    def test_the_box_is_kept_and_saved_as_a_change(self):
        templates = {}
        workflow_editing.set_template(templates, "release", "T1", [["Quality"]], require_eco=True)
        workflow_editing.set_template(templates, "release", "T2", [["Quality"]])
        editor = workflow_editor.WorkflowEditor(templates)
        self.assertEqual([i["eco"] for i in editor.items["release"]], [True, False])
        self.assertEqual(editor.ops(), [])
        editor.items["release"][1]["eco"] = True
        ops = editor.ops()
        self.assertEqual([(op["name"], op["eco"]) for op in ops], [("T2", True)])
        workflow_editing.apply_ops(templates, ops)
        self.assertTrue(templates["release"]["T2"].require_eco)
        self.assertTrue(editor.templates()["release"]["T2"].require_eco)

    def test_new_workflows_start_unticked(self):
        editor = workflow_editor.WorkflowEditor({})
        editor.add("release", ["Quality"])
        self.assertFalse(editor.items["release"][0]["eco"])

    def test_only_the_standard_release_t1_requires_an_eco(self):
        editor = workflow_editor.WorkflowEditor({})
        editor.add_standard(["Responsible Engineer", "Manufacturing", "Analysis", "Manager", "Chief"])
        ticked = [(action, i["name"]) for action, items in editor.items.items() for i in items if i["eco"]]
        self.assertEqual(ticked, [("release", "T1")])
        templates = {}
        workflow_editing.add_standard(templates, SimpleNamespace(roles=[]))
        ticked = [(a, n) for a, named in templates.items() for n, t in named.items() if t.require_eco]
        self.assertEqual(ticked, [("release", "T1")])
