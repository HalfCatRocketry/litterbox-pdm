"""Tests for gui/logic/history_text.py: history events, revision lists."""

import tempfile
import unittest
from litterbox.gui.logic import history_text
from litterbox.gui.logic import list_view
from litterbox.gui.logic import opening_text
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.core.part_number import PN
from tests.support.part_rows import revised


class TestRevisions(unittest.TestCase):
    A = ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"]
    B = ["cad/HCR-00007-001_B.SLDPRT"]

    def test_open_offers_both_revisions_when_there_is_a_released_and_a_working_one(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        self.assertEqual(opening_text.open_choices(part), [("B", self.B), ("A", self.A)])        # working first
        self.assertEqual(history_text.revision_label(part, "B"), "Rev B (working)")
        self.assertEqual(history_text.revision_label(part, "A"), "Rev A (released)")

    def test_open_drawing_only_offers_revisions_that_have_one(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        self.assertEqual(opening_text.open_choices(part, drawing=True), [("A", self.A)])          # no prompt needed
        self.assertEqual(opening_text.open_message(part, drawing=True), "")
        only_b = revised(7, "B", "A", {"B": self.B})
        self.assertIn("no drawing", opening_text.open_message(only_b, drawing=True))

    def test_one_revision_means_no_question(self):
        released = revised(7, "A", "A", {"A": self.A}, status="released")
        self.assertEqual(opening_text.open_choices(released), [("A", self.A)])
        self.assertEqual(history_text.revision_label(released, "A"), "Rev A (released)")
        working_only = revised(7, "A", "", {"A": self.A})
        self.assertEqual(opening_text.open_choices(working_only), [("A", self.A)])
        self.assertEqual(history_text.revision_label(working_only, "A"), "Rev A (working)")

    def test_released_revision_is_opened_when_the_working_one_has_no_files_yet(self):
        part = revised(7, "B", "A", {"A": self.A})
        self.assertEqual(opening_text.open_choices(part), [("A", self.A)])

    def test_released_view_includes_a_part_with_a_released_revision_while_a_new_one_is_in_work(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        plain = revised(8, "A", "", {"A": self.A})
        self.assertEqual(list_view.filter_rows([part, plain], view="Released"), [part])

    def test_revision_rows_for_the_history_window(self):
        record = record_model.Record(pn=PN("HCR", 7, 1), name="Part", created_by="Alex", created_at="2026-10-01T10:00:00Z",
                                 revision="B", released_revision="A")
        record.history = [{"event": "released", "by": "Jo", "at": "2026-10-02T10:00:00Z", "revision": "A"}]
        rows = history_text.revision_rows(record, {"A": self.A, "B": self.B})
        self.assertEqual([r[:2] for r in rows], [("B", "In work"), ("A", "Released")])
        self.assertIn("by Jo", rows[1][2])
        self.assertIn("DRW, PRT", rows[1][2])
        record.released_revision = "B"
        record.status = "released"
        record.history.append({"event": "released", "by": "Bea", "at": "2026-10-09T10:00:00Z", "revision": "B"})
        self.assertEqual([r[:2] for r in history_text.revision_rows(record, {})],
                         [("B", "Released"), ("A", "Released (superseded)")])


class TestHistory(unittest.TestCase):
    def test_time_formatting(self):
        self.assertEqual(history_text.to_display_time("2026-10-05T14:02:41Z", local=False), "2026-10-05 14:02")
        self.assertEqual(history_text.to_display_time("garbage"), "garbage")
        self.assertRegex(history_text.to_display_time("2026-10-05T14:02:41Z"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_rows_are_newest_first_with_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = record_store.create_record(tmp, PN("HCR", 1, 1), "Front upright", "Alex")
            files = ["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW"]
            record_lifecycle.record_checkout(record, "Alex", files)
            record_lifecycle.record_checkin(record, "Alex", files[:1], "Added fillet")
            record_lifecycle.mark_released(record, "Jo", files)
            record_lifecycle.mark_reopened(record, "Jo", "Bore wrong")
        rows = history_text.format_history(record, local=False)
        self.assertEqual([r[2] for r in rows], ["Unreleased", "Released", "Checked in", "Checked out", "Created"])
        self.assertEqual(rows[0][1:], ("Jo", "Unreleased", "Bore wrong"))
        self.assertEqual(rows[2][3], "Added fillet  -  HCR-00001-001_A.SLDPRT")
        self.assertEqual(rows[3][3], "HCR-00001-001_A.SLDPRT, HCR-00001-001_A.SLDDRW")
        self.assertEqual(rows[4][3], "")


class TestWorkflowHistory(unittest.TestCase):
    def history(self, *events):
        from litterbox.records import record_model
        from litterbox.core.part_number import parse
        record = record_model.Record(parse("HCR-00001-001"), "Upright", "Alex", "2026-10-11T00:00:00Z")
        for event in events:
            record.history.append(dict({"by": "Bea", "at": "2026-10-11T01:00:00Z", "revision": "A"}, **event))
        return history_text.format_history(record, local=False)

    def test_labels_and_details(self):
        rows = self.history(
            {"event": "release_requested", "waiting_on": ["Quality (0 of 1)"]},
            {"event": "release_signed", "roles": ["Quality"], "comment": "ok"},
            {"event": "release_rejected", "reason": "Missing tolerance", "signed": ["Alex Smith"]},
            {"event": "release_withdrawn", "reason": "Wrong rev"},
            {"event": "released", "signoffs": ["Alex Smith", "Bea Jones"]},
            {"event": "released", "override": True, "reason": "Urgent"})
        by_label = {r[2]: r[3] for r in rows}
        self.assertEqual(by_label["Release requested"], "needs Quality (0 of 1)")
        self.assertEqual(by_label["Signed off"], "ok  -  as Quality")
        self.assertEqual(by_label["Release rejected"], "Missing tolerance  -  had been signed by Alex Smith")
        self.assertEqual(by_label["Request withdrawn"], "Wrong rev")
        self.assertEqual(by_label["Released"], "signed off by Alex Smith, Bea Jones")
        self.assertEqual(by_label["Released (Admin override)"], "Urgent")


if __name__ == "__main__":
    unittest.main()
