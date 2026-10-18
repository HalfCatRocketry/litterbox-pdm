"""Tests for gui/logic/reference_text.py."""

import unittest
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import confirmations
from litterbox.gui.logic import history_text
from litterbox.gui.logic import reference_text
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.core.part_number import PN


class TestReferenceText(unittest.TestCase):
    def use(self, **kw):
        from types import SimpleNamespace as S
        values = dict(parent=PN("HCR", 2, 1), parent_revision="A", parent_name="Frame", parent_status="in_work",
                      child=PN("HCR", 1, 1), child_revision="A", child_name="Upright", latest_released="B",
                      state_text="Newer revision released (Rev B)", replaceable=True)
        values.update(kw)
        return S(**values)

    def test_tables(self):
        (iid, values, can), = reference_text.uses_table([self.use()])
        self.assertEqual((iid, can, values[0], values[1], values[3], values[4]),
                         ("0", True, reference_text.CHECKED, "00001-001", "A", "B"))
        (iid, values, can), = reference_text.used_in_table([self.use(replaceable=False, parent_status="released")])
        self.assertEqual((can, values[0], values[1], values[4], values[5]), (False, "", "00002-001", "Released", "A"))

    def test_toggled(self):
        self.assertEqual(reference_text.toggled(reference_text.CHECKED), reference_text.UNCHECKED)
        self.assertEqual(reference_text.toggled(reference_text.UNCHECKED), reference_text.CHECKED)
        self.assertEqual(reference_text.toggled(""), "")

    def test_release_text_shows_warnings(self):
        from types import SimpleNamespace as S
        plan = S(pn=PN("HCR", 2, 1), name="Frame", files=["cad/a.SLDASM"], warnings=["It uses X Rev A."])
        text = confirmations.release_confirm_text(plan)
        self.assertIn("WARNING", text); self.assertIn("It uses X Rev A.", text)
        plan.warnings = []
        self.assertNotIn("WARNING", confirmations.release_confirm_text(plan))

    def test_stale_open_text_and_replace_summary(self):
        self.assertIn("Rev B is released", reference_text.stale_open_text(PN("HCR", 2, 1), [self.use()]))
        from litterbox.references.reference_replace import ReplaceResult
        text, problems = reference_text.replace_summary([ReplaceResult(PN("HCR", 2, 1), "done", "ok"),
                                                ReplaceResult(PN("HCR", 3, 1), "skipped", "Checked out by Bea.")])
        self.assertTrue(problems)
        self.assertIn("1 of 2", text); self.assertIn("Checked out by Bea.", text)
        self.assertFalse(reference_text.replace_summary([ReplaceResult(PN("HCR", 2, 1), "done")])[1])

    def test_history_shows_references(self):
        record = record_model.Record(pn=PN("HCR", 2, 1), name="x", created_by="a", created_at="t")
        record_lifecycle.add_event(record, "checked_in", "Alex", files=["cad/a.SLDASM"], references=["HCR-00001-001_A"])
        self.assertIn("uses HCR-00001-001_A", history_text.format_history(record)[0][3])

    def test_outdated_note_and_update_summary(self):
        pn = PN("HCR", 2, 1)
        self.assertEqual(reference_text.outdated_note(pn, False, []), "")
        self.assertIn("00002-001", reference_text.outdated_note(pn, True, []))
        self.assertIn("2 other assemblies", reference_text.outdated_note(pn, False, [1, 2]))
        text, problems = reference_text.update_summary({pn: "updated", PN("HCR", 3, 1): "skipped: checked out by Bea."})
        self.assertTrue(problems)
        self.assertIn("1 of 2", text); self.assertIn("checked out by Bea", text)
        self.assertFalse(reference_text.update_summary({pn: "unchanged"})[1])

    def test_references_button_works_on_any_downloaded_part(self):
        self.assertIn("released", action_rules.ALLOWED_KINDS["references"])
        self.assertIn("unclaimed", action_rules.ALLOWED_KINDS["references"])


if __name__ == "__main__":
    unittest.main()
