"""Tests for the window's side of Purchasing Info, the BOM tab and Export Files: the buttons' rules and the words."""

import tempfile
import unittest
from pathlib import Path

from litterbox.core.part_number import PN
from litterbox.exporting import part_files_export
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import bom_text
from litterbox.gui.logic import export_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import part_details_text
from litterbox.gui.logic import purchasing_text
from litterbox.parts import purchasing
from litterbox.records import record_model
from litterbox.references import bom
from tests.support.part_rows import BY_PN


def pns(*bases):
    return [PN("HCR", b, 1) for b in bases]


class Buttons(unittest.TestCase):
    def test_purchasing_info_works_on_any_part_but_void_or_someone_elses(self):
        for base in (1, 2, 4, 6):                    # available, mine, released, modified
            self.assertEqual(action_rules.plan_action("purchasing", pns(base), BY_PN).targets, pns(base))
        self.assertIn("Can't change the purchasing info of", action_rules.plan_action("purchasing", pns(3), BY_PN).message)
        self.assertIn("Can't change the purchasing info of", action_rules.plan_action("purchasing", pns(5), BY_PN).message)
        self.assertIn("just one", action_rules.plan_action("purchasing", pns(1, 4), BY_PN).message)

    def test_export_files_takes_the_ticked_parts_or_else_the_highlighted_one(self):
        self.assertEqual(action_rules.choose_targets("export_files", pns(1, 4), pns(6)), pns(1, 4))
        self.assertEqual(action_rules.choose_targets("export_files", [], pns(6)), pns(6))
        self.assertEqual(action_rules.plan_action("export_files", pns(1, 2, 3, 4, 5, 6), BY_PN).targets,
                         pns(1, 2, 3, 4, 5, 6))

    def test_export_files_still_works_on_a_part_with_a_job_running(self):
        busy = {"HCR-00001-001": "Checking in"}
        self.assertEqual(action_rules.plan_action("export_files", pns(1), BY_PN, busy).targets, pns(1))
        self.assertTrue(action_rules.action_available("export_files", pns(1), [], BY_PN, busy))
        self.assertFalse(action_rules.action_available("purchasing", pns(1), [], BY_PN, busy))


class Purchasing(unittest.TestCase):
    def test_what_was_typed(self):
        old = {"supplier": "Acme"}
        self.assertEqual(purchasing_text.dialog_result(old, {"supplier": " Acme ", "unit_cost": ""}), ("", None))
        problem, fields = purchasing_text.dialog_result(old, {"unit_cost": "abc"})
        self.assertIn("must be a number", problem)
        self.assertIsNone(fields)
        self.assertEqual(purchasing_text.dialog_result(old, {"unit_cost": "$3"}),
                         ("", {"supplier": "Acme", "supplier_pn": "", "unit_cost": "3", "lead_time_days": ""}))

    def test_the_details_tab_shows_the_filled_in_fields(self):
        record = record_model.Record(pn=PN("HCR", 1, 1), name="Bolt", created_by="Alex", created_at="t",
                                     purchasing={"supplier": "Acme", "lead_time_days": 3})
        fields = dict(part_details_text.revision_details(record, "A", {}))
        self.assertEqual((fields["Supplier"], fields["Lead time (days)"]), ("Acme", "3"))
        self.assertNotIn("Unit cost", fields)

    def test_the_history_names_the_event(self):
        record = record_model.Record(pn=PN("HCR", 1, 1), name="Bolt", created_by="Alex", created_at="t",
                                     history=[{"event": "purchasing_edited", "by": "Alex", "at": "x",
                                               "changes": ["supplier: '' -> 'Acme'"]}])
        self.assertEqual(history_text.format_history(record)[0][2:], ("Purchasing info", "supplier: '' -> 'Acme'"))

    def test_the_status_line_afterwards(self):
        self.assertIn("Check In to upload", purchasing_text.done_text("HCR-1", purchasing.SAVED_LOCALLY))
        self.assertIn("already", purchasing_text.done_text("HCR-1", purchasing.UNCHANGED))
        self.assertEqual(purchasing_text.done_text("HCR-1", purchasing.UPLOADED), "Updated the purchasing info of HCR-1.")


class BomTab(unittest.TestCase):
    def lines(self):
        return [bom.BomLine(1, PN("HCR", 2, 1), "A", "Frame", sub_assembly=True),
                bom.BomLine(2, PN("HCR", 4, 1), "B", "Bolt", purchasing={"supplier": "Acme", "lead_time_days": 3})]

    def test_an_indented_table_pushes_parts_right_by_level(self):
        rows = bom_text.table(self.lines(), bom.INDENTED)
        self.assertEqual(rows[0][1][0], "00002-001")
        self.assertEqual(rows[1][1][:6], ("    00004-001", "B", "Bolt", "Acme", "", "3 days"))
        self.assertEqual(bom_text.table(self.lines(), bom.SINGLE)[1][1][0], "00004-001")

    def test_the_line_above_the_table(self):
        self.assertIn("uses no other parts", bom_text.note([], False))
        text = bom_text.note(self.lines(), True, outdated=True)
        self.assertTrue(text.startswith("2 lines. Its list of parts used is out of date"))
        self.assertIn("No quantities", text)


class Exports(unittest.TestCase):
    def test_the_folder_offered_first(self):
        with tempfile.TemporaryDirectory() as there:
            self.assertEqual(export_text.start_folder({"export_folder": there}, home="H"), there)
        self.assertEqual(export_text.start_folder({"export_folder": "Z:/gone/away"}, home="H"), "H")
        self.assertEqual(export_text.start_folder({}, home="H"), "H")

    def test_words(self):
        plan = part_files_export.ExportPlan(files=["a", "b"], notes=["X was never released."])
        self.assertEqual(export_text.plan_lines(plan), ["2 files to copy.", "X was never released."])
        self.assertIn("Replace them", export_text.replace_question(Path("out"), ["a.STEP"]))
        self.assertEqual(export_text.exported_text("out", ["a"]), "Exported 1 file to out.")


if __name__ == "__main__":
    unittest.main()
