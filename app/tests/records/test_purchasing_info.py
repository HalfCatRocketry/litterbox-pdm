"""Tests for a part's purchasing information: checking the fields, keeping them in the record, and changing them."""

import unittest

import yaml

from litterbox.core.part_number import PN
from litterbox.records import purchasing_info
from litterbox.records import record_lifecycle
from litterbox.records import record_model


def record(**fields):
    return record_model.Record(pn=PN("HCR", 7, 1), name="Bolt", created_by="Alex", created_at="t", **fields)


def round_trip(rec):
    return record_model.Record.from_dict(yaml.safe_load(record_model.dump(rec)))


class Fields(unittest.TestCase):
    def test_cost_is_kept_as_typed_text_without_currency_signs_or_commas(self):
        self.assertEqual(purchasing_info.clean_cost("$1,234.50"), "1234.50")
        self.assertEqual(purchasing_info.clean_cost("0.10"), "0.10")
        self.assertEqual(purchasing_info.clean_cost(".5"), "0.5")
        self.assertEqual(purchasing_info.clean_cost("12."), "12")
        self.assertEqual(purchasing_info.clean_cost(" "), "")
        self.assertEqual(purchasing_info.clean_cost(0.25), "0.25")         # a hand-edited record: YAML gave a float

    def test_bad_costs_say_why(self):
        for bad, why in (("-1", "zero or more"), ("ten", "a number"), ("1e3", "a number"), ("1.23456", "decimal"),
                         ("1.2.3", "a number")):
            with self.assertRaisesRegex(purchasing_info.PurchasingError, why, msg=bad):
                purchasing_info.clean_cost(bad)

    def test_lead_time_is_whole_days(self):
        self.assertEqual(purchasing_info.clean_lead_time("14"), 14)
        self.assertEqual(purchasing_info.clean_lead_time(0), 0)
        self.assertIsNone(purchasing_info.clean_lead_time(""))
        for bad in ("2 weeks", "1.5", "-1", "3651", True):
            with self.assertRaises(purchasing_info.PurchasingError, msg=bad):
                purchasing_info.clean_lead_time(bad)

    def test_clean_leaves_out_empty_fields_and_keeps_unknown_ones(self):
        cleaned = purchasing_info.clean({"supplier": "  McMaster   Carr ", "supplier_pn": "", "unit_cost": "",
                                         "lead_time_days": "", "moq": 100})
        self.assertEqual(cleaned, {"supplier": "McMaster Carr", "moq": 100})
        self.assertEqual(purchasing_info.clean(None), {})
        with self.assertRaises(purchasing_info.PurchasingError):
            purchasing_info.clean(["not", "a", "section"])
        with self.assertRaisesRegex(purchasing_info.PurchasingError, "at most"):
            purchasing_info.clean({"supplier": "x" * 101})

    def test_changes_name_each_field_that_changed(self):
        self.assertEqual(purchasing_info.changes({"supplier": "A"}, {"supplier": "B", "lead_time_days": 3}),
                         ["supplier: 'A' -> 'B'", "lead time (days): '' -> '3'"])


class InTheRecord(unittest.TestCase):
    def test_a_record_without_purchasing_has_no_section(self):
        self.assertNotIn("purchasing", record().to_dict())
        self.assertEqual(round_trip(record()).purchasing, {})

    def test_the_section_survives_a_round_trip_with_numbers_kept_as_text(self):
        rec = record(purchasing={"supplier": "McMaster-Carr", "supplier_pn": "00123", "unit_cost": "0.10",
                                 "lead_time_days": 3})
        text = record_model.dump(rec)
        self.assertIn("unit_cost: '0.10'", text)
        self.assertIn("supplier_pn: '00123'", text)
        self.assertEqual(round_trip(rec).purchasing, rec.purchasing)
        self.assertEqual(round_trip(rec).extra, {})

    def test_a_bad_section_makes_the_record_unreadable_with_a_reason(self):
        data = record().to_dict()
        data["purchasing"] = {"unit_cost": "cheap"}
        with self.assertRaisesRegex(record_model.RegistryError, "HCR-00007-001: Unit cost"):
            record_model.Record.from_dict(data)


class Editing(unittest.TestCase):
    def test_a_change_is_recorded_in_the_history(self):
        rec = record()
        event = record_lifecycle.edit_purchasing(rec, "Alex", {"supplier": "Acme", "unit_cost": "$2.5"})
        self.assertEqual(rec.purchasing, {"supplier": "Acme", "unit_cost": "2.5"})
        self.assertEqual(event["event"], record_model.EVENT_PURCHASING_EDITED)
        self.assertEqual(event["changes"], ["supplier: '' -> 'Acme'", "unit cost: '' -> '2.5'"])

    def test_fields_left_out_keep_their_values_and_empty_ones_clear(self):
        rec = record(purchasing={"supplier": "Acme", "lead_time_days": 5})
        record_lifecycle.edit_purchasing(rec, "Alex", {"lead_time_days": ""})
        self.assertEqual(rec.purchasing, {"supplier": "Acme"})

    def test_no_change_adds_nothing(self):
        rec = record(purchasing={"supplier": "Acme"})
        self.assertIsNone(record_lifecycle.edit_purchasing(rec, "Alex", {"supplier": " Acme "}))
        self.assertEqual(rec.history, [])

    def test_released_and_cots_parts_take_it_but_void_ones_do_not(self):
        for status, cots in ((record_model.STATUS_RELEASED, False), (record_model.STATUS_IN_WORK, True)):
            rec = record(status=status, cots=cots)
            self.assertIsNotNone(record_lifecycle.edit_purchasing(rec, "Alex", {"supplier": "Acme"}))
        with self.assertRaisesRegex(record_model.RegistryError, "void"):
            record_lifecycle.edit_purchasing(record(status=record_model.STATUS_VOID), "Alex", {"supplier": "Acme"})

    def test_a_bad_value_changes_nothing(self):
        rec = record(purchasing={"supplier": "Acme"})
        with self.assertRaisesRegex(record_model.RegistryError, "Unit cost"):
            record_lifecycle.edit_purchasing(rec, "Alex", {"supplier": "B", "unit_cost": "lots"})
        self.assertEqual(rec.purchasing, {"supplier": "Acme"})


if __name__ == "__main__":
    unittest.main()
