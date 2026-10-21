"""Tests for the window's side of Generate STEP/PDF and the Export Files revision list: the table of what will
happen to each part, the Details tab's STEP/PDF line, and the revisions offered."""

import unittest
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.exporting import part_files_export
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import export_text
from litterbox.gui.logic import generate_text
from litterbox.gui.logic import part_details_text
from litterbox.records import record_exports
from litterbox.records import record_lifecycle
from litterbox.records import record_model

BOTH = list(record_exports.KINDS)
PRT, DRW, STEP, PDF = ("cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.STEP",
                       "cad/HCR-00001-001_A.PDF")


def row(kind="ok", files=(PRT, DRW), locked_by="", needed=(), revision="A", released="", status="in_work",
        released_revisions=()):
    return SimpleNamespace(pn=PN("HCR", 1, 1), name="Bracket", kind=kind, files=list(files), locked_by=locked_by,
                           files_needed=tuple(needed), revision=revision, released_revision=released,
                           record_status=status, released_revisions=tuple(released_revisions), state=kind)


def what(part, kinds=BOTH, where=generate_text.IN_VAULT, force=False):
    return generate_text.row_text(part, kinds, where, force)


class Table(unittest.TestCase):
    def test_in_the_vault(self):
        self.assertEqual(what(row()), ("STEP and PDF made and uploaded now", True))
        self.assertEqual(what(row("mine")), ("STEP and PDF made in your checkout, uploaded at Check In", True))
        self.assertEqual(what(row("theirs", locked_by="Bea")), ("Checked out by Bea: skipped", False))
        self.assertEqual(what(row("pending")), ("Waiting for sign-offs: skipped", False))
        self.assertEqual(what(row("unclaimed")), ("Has changes that are not checked in: skipped", False))

    def test_missing_model_or_drawing(self):
        self.assertEqual(what(row(files=[PRT])), ("STEP made and uploaded now (STEP only: no drawing)", True))
        self.assertEqual(what(row(files=[PRT]), kinds=[record_exports.PDF]), ("No drawing: skipped", False))
        self.assertEqual(what(row(files=[])), ("No model or drawing: skipped", False))

    def test_released_parts_are_skipped_when_up_to_date_unless_forced(self):
        flagged = row("released", files=[PRT, DRW, STEP, PDF], needed=BOTH)
        current = row("released", files=[PRT, DRW, STEP, PDF])
        missing = row("released", files=[PRT, DRW, STEP])
        self.assertTrue(what(flagged)[1])
        self.assertEqual(what(current), ("Released, up to date: skipped", False))
        self.assertEqual(what(current, force=True), ("STEP and PDF made again and uploaded now", True))
        self.assertTrue(what(missing)[1])
        self.assertTrue(generate_text.any_up_to_date([current], BOTH))
        self.assertFalse(generate_text.any_up_to_date([flagged], BOTH))

    def test_outside_anything_with_a_model_or_drawing_is_saved(self):
        for kind in ("theirs", "pending", "released", "unclaimed"):
            self.assertEqual(what(row(kind), where=generate_text.OUTSIDE), ("STEP and PDF saved to the folder", True))

    def test_counts_and_summaries(self):
        table = generate_text.table([row(), row("theirs", locked_by="Bea")], BOTH, generate_text.IN_VAULT)
        self.assertEqual(generate_text.count_text(table), "1 part, 1 skipped")
        result = SimpleNamespace(done=[(PN("HCR", 1, 1), [STEP, PDF])], failed=[("x", "y")])
        self.assertEqual(generate_text.done_text(result), "Made 2 files for 1 part, 1 failed")


class Menu(unittest.TestCase):
    def test_it_takes_the_ticked_parts_or_else_the_highlighted_one_and_never_void_ones(self):
        pns = [PN("HCR", 1, 1)]
        self.assertEqual(action_rules.choose_targets("generate_step_pdf", [], pns), pns)
        self.assertEqual(action_rules.plan_action("generate_step_pdf", pns, {pns[0]: row("released")}).targets, pns)
        self.assertIn("Can't make the STEP/PDF of",
                      action_rules.plan_action("generate_step_pdf", pns, {pns[0]: row("void")}).message)


class DetailsTab(unittest.TestCase):
    def setUp(self):
        self.record = record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "2026-10-21T10:00:00Z")
        self.revisions = {"A": [PRT, DRW]}

    def test_a_flagged_release_says_what_it_needs(self):
        record_lifecycle.mark_released(self.record, "Alex", [PRT, DRW])
        self.assertEqual(part_details_text.files_flagged(self.record, "A", self.revisions), BOTH)
        self.assertEqual(part_details_text.files_made_text(self.record, "A", self.revisions),
                         "STEP and PDF need updating")
        fields = dict(part_details_text.revision_details(self.record, "A", self.revisions))
        self.assertEqual(fields["STEP/PDF"], "STEP and PDF need updating")

    def test_made_files_say_who_made_them(self):
        record_lifecycle.mark_released(self.record, "Alex", [PRT, DRW])
        record_exports.record_made(self.record, "Bea", "A", {"step": {"file": STEP}}, BOTH)
        text = part_details_text.files_made_text(self.record, "A", self.revisions, local=False)
        self.assertTrue(text.startswith("PDF needs updating; STEP made by Bea on "), text)

    def test_nothing_is_said_when_nothing_was_made_or_needed(self):
        self.assertEqual(part_details_text.files_made_text(self.record, "A", self.revisions), "")
        self.assertNotIn("STEP/PDF", dict(part_details_text.revision_details(self.record, "A", self.revisions)))


class ExportRevisions(unittest.TestCase):
    def test_one_part_lists_working_then_every_release_newest_first(self):
        choices, first = export_text.revision_choices([row(revision="C", released="B", released_revisions="AB")])
        self.assertEqual(choices, [("Working (Rev C)", part_files_export.WORKING), ("Rev B (Latest released)", "B"),
                                   ("Rev A", "A")])
        self.assertEqual(first, "Rev B (Latest released)")

    def test_a_released_working_revision_is_listed_once(self):
        choices, first = export_text.revision_choices(
            [row(revision="B", released="B", status="released", released_revisions="AB")])
        self.assertEqual(choices, [("Rev B (Latest released)", "B"), ("Rev A", "A")])
        self.assertEqual(first, "Rev B (Latest released)")

    def test_a_part_never_released_offers_its_working_revision(self):
        self.assertEqual(export_text.revision_choices([row()]),
                         ([("Working (Rev A)", part_files_export.WORKING)], "Working (Rev A)"))

    def test_a_reopened_revision_is_the_working_one(self):
        choices, _first = export_text.revision_choices([row(revision="B", released="A", released_revisions="AB")])
        self.assertEqual([which for _label, which in choices], [part_files_export.WORKING, "A"])

    def test_several_parts_get_latest_released_and_working(self):
        choices, first = export_text.revision_choices([row(), row()])
        self.assertEqual([label for label, _which in choices], ["Latest released", "Working"])
        self.assertEqual(first, "Latest released")


if __name__ == "__main__":
    unittest.main()
