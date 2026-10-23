"""Tests that an older Litterbox never loses or misreads what a newer one wrote, and that every event says who did
it by team id as well as by name: the record format number, unknown fields kept in people.yaml, workflows.yaml and
ECO files, and util/person_name.py."""

import unittest

import yaml

from litterbox import layout
from litterbox.change_orders import eco_lifecycle
from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store
from litterbox.core.part_number import PN
from litterbox.records import record_lifecycle
from litterbox.records import record_migrations
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.team import team_model
from litterbox.util import person_name
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_store
from tests.support.registry_case import RegistryTestCase


ALEX = person_name.PersonName("Alex Smith", "alex")


class RecordFormat(RegistryTestCase):
    def test_new_records_say_their_format(self):
        self.make(42)
        text = (self.repo / "PN-logs" / "HCR-00042-001.yaml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(f"format: {record_migrations.current_format()}\n"))

    def test_a_record_without_a_format_is_format_1(self):
        data = record_model.Record(PN("HCR", 1, 1), "Old part", "Alex", "2026-01-01T00:00:00Z").to_dict()
        del data["format"]
        self.assertEqual(record_model.Record.from_dict(data).name, "Old part")

    def test_a_record_from_a_newer_litterbox_is_refused_with_advice(self):
        data = record_model.Record(PN("HCR", 1, 1), "New part", "Alex", "2026-01-01T00:00:00Z").to_dict()
        data["format"] = record_migrations.current_format() + 1
        with self.assertRaisesRegex(record_model.RegistryError, "newer Litterbox"):
            record_model.Record.from_dict(data)
        for bad in ("2", True, 0):
            data["format"] = bad
            with self.assertRaises(record_model.RegistryError):
                record_model.Record.from_dict(data)


class PeopleFileKeepsUnknownFields(unittest.TestCase):
    def test_round_trip(self):
        data = {"roles": ["Quality"], "projects_policy": {"Rover": ["alex"]},
                "people": [{"id": "alex", "name": "Alex", "host_names": ["alexs"], "access": "owner",
                            "roles": ["Quality"], "active": True, "badge": 7}]}
        out = team_model.from_dict(data).to_dict()
        self.assertEqual(out["projects_policy"], {"Rover": ["alex"]})
        self.assertEqual(out["people"][0]["badge"], 7)
        self.assertEqual(out["people"][0]["name"], "Alex")


class WorkflowsFileKeepsUnknownFields(RegistryTestCase):
    def write(self, data):
        path = self.repo / layout.WORKFLOWS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    def test_saving_keeps_unknown_template_fields_and_sections(self):
        path = self.write({"workflows": {"release": {"T1": {"signoffs": [{"roles": ["Quality"]}], "deadline_days": 5},
                                                     "T2": {"signoffs": [{"roles": ["Quality"]}]}}},
                           "escalation": {"after_days": 3}})
        templates = workflow_store.load(self.repo)
        workflow_editing.set_template(templates, "release", "T1 renamed", [["Quality"]], old_name="T1")
        workflow_store.save(self.repo, templates)
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["escalation"], {"after_days": 3})
        self.assertEqual(saved["workflows"]["release"]["T1 renamed"]["deadline_days"], 5)
        self.assertNotIn("deadline_days", saved["workflows"]["release"]["T2"])


class EcoFileKeepsUnknownFields(unittest.TestCase):
    def test_round_trip(self):
        data = {"number": "ECO-0001", "name": "Change", "status": "open", "priority": "high",
                "parts": [{"pn": "HCR-00042-001", "revision": "A", "disposition": "rework"}],
                "requested_by": "Alex", "requested_by_id": "alex", "history": []}
        eco = eco_model.Eco.from_dict(data)
        self.assertEqual(eco.requested_by_id, "alex")
        out = eco.to_dict()
        self.assertEqual(out["priority"], "high")
        self.assertEqual(out["parts"][0]["disposition"], "rework")
        self.assertEqual(out["requested_by_id"], "alex")


class EveryEventSaysWhoById(RegistryTestCase):
    def test_person_name_is_a_name_with_an_id(self):
        self.assertEqual(ALEX, "Alex Smith")
        self.assertEqual(person_name.id_of(ALEX), "alex")
        self.assertEqual(person_name.id_of("Alex Smith"), "")
        self.assertEqual(person_name.stamp({}, "by", ALEX), {"by": "Alex Smith", "by_id": "alex"})
        self.assertEqual(person_name.stamp({}, "by", "Alex Smith"), {"by": "Alex Smith"})
        self.assertEqual(yaml.safe_dump({"by": ALEX}), "by: Alex Smith\n")

    def test_creating_and_events_record_the_id(self):
        record = record_store.create_record(self.repo, PN("HCR", 42, 1), "Bracket", ALEX)
        self.assertEqual((record.created_by, record.created_by_id), ("Alex Smith", "alex"))
        self.assertEqual(record.history[0]["by_id"], "alex")
        entry = record_lifecycle.add_event(record, record_model.EVENT_EDITED, ALEX)
        self.assertEqual((entry["by"], entry["by_id"]), ("Alex Smith", "alex"))
        self.assertIs(type(entry["by"]), str)
        loaded = record_store.load(self.repo, PN("HCR", 42, 1))
        self.assertEqual(loaded.created_by_id, "alex")

    def test_without_a_team_there_is_no_id(self):
        record = record_store.create_record(self.repo, PN("HCR", 43, 1), "Plate", "Alex Smith")
        self.assertEqual(record.created_by_id, "")
        self.assertNotIn("by_id", record.history[0])
        self.assertNotIn("created_by_id", record.to_dict())

    def test_ecos_record_the_id(self):
        eco = eco_lifecycle.open_eco(self.repo, "Change", "Why", "release", "T1", "req-1", [(PN("HCR", 42, 1), "A")], ALEX)
        self.assertEqual((eco.requested_by, eco.requested_by_id), ("Alex Smith", "alex"))
        self.assertEqual(eco.history[0]["by_id"], "alex")
        self.assertEqual(eco_store.load(self.repo, eco.number).requested_by_id, "alex")


if __name__ == "__main__":
    unittest.main()
