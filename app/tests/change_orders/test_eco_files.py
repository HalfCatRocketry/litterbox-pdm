"""Tests for change_orders/: what an ECO holds, its file, and opening and closing one (no git)."""

import os
import unittest
from litterbox.change_orders import eco_lifecycle
from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store
from litterbox.core.part_number import PN
from litterbox.records import record_store
from litterbox.workflows import workflow_templates
from tests.support.registry_case import RegistryTestCase


def an_eco(number="ECO-0001", **fields):
    return eco_model.Eco(number, "New bracket", "Thicker wall", parts=[{"pn": "HCR-00001-001", "revision": "A"}],
                         **fields)


class TestModel(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(eco_model.number_text(3), "ECO-0003")
        self.assertEqual(eco_model.number_value("ECO-0003"), 3)
        self.assertEqual(eco_model.number_value("ECO-12345"), 12345)
        for bad in ("ECO-3", "eco-0003", "ECO-0003.yaml", "", None):
            self.assertIsNone(eco_model.number_value(bad))

    def test_a_name_is_required_and_tidied(self):
        self.assertEqual(eco_model.clean_name("  New   bracket "), "New bracket")
        with self.assertRaises(eco_model.EcoError):
            eco_model.clean_name("   ")
        with self.assertRaises(eco_model.EcoError):
            eco_model.clean_name("x" * (eco_model.MAX_NAME + 1))

    def test_the_description_is_optional_but_limited(self):
        self.assertEqual(eco_model.clean_description(None), "")
        self.assertEqual(eco_model.clean_description(" line one\nline two \n"), "line one\nline two")
        with self.assertRaises(eco_model.EcoError):
            eco_model.clean_description("x" * (eco_model.MAX_DESCRIPTION + 1))

    def test_round_trip(self):
        eco = an_eco(signoffs=[{"id": "bea", "by": "Bea Jones"}], history=[{"event": "opened", "by": "Alex"}])
        self.assertEqual(eco_model.Eco.from_dict(eco.to_dict()), eco)
        self.assertNotIn("signoffs", an_eco().to_dict())

    def test_bad_files_are_refused(self):
        for data in ([], {"number": "7"}, {"number": "ECO-0001", "status": "maybe"},
                     {"number": "ECO-0001", "parts": [{"revision": "A"}]}):
            with self.assertRaises(eco_model.EcoError):
                eco_model.Eco.from_dict(data)

    def test_closed(self):
        self.assertFalse(an_eco().closed)
        for status in eco_model.CLOSED:
            self.assertTrue(an_eco(status=status).closed)


class TestStore(RegistryTestCase):
    def test_numbers_follow_the_highest_used(self):
        self.assertEqual(eco_store.next_number(self.repo), "ECO-0001")
        eco_store.save(self.repo, an_eco("ECO-0001"))
        eco_store.save(self.repo, an_eco("ECO-0004"))
        (self.repo / "ECO" / "notes.yaml").write_text("x")              # not an ECO: ignored
        self.assertEqual(eco_store.numbers(self.repo), ["ECO-0001", "ECO-0004"])
        self.assertEqual(eco_store.next_number(self.repo), "ECO-0005")

    def test_saved_files_are_read_only_and_load_back(self):
        rel = eco_store.save(self.repo, an_eco())
        self.assertEqual(rel, "ECO/ECO-0001.yaml")
        self.assertFalse(os.access(self.repo / rel, os.W_OK))
        eco = eco_store.load(self.repo, "ECO-0001")
        eco.status = eco_model.RELEASED
        eco_store.save(self.repo, eco)                 # Litterbox itself can still change it
        self.assertEqual(eco_store.load(self.repo, "ECO-0001").status, eco_model.RELEASED)
        self.assertFalse(os.access(self.repo / rel, os.W_OK))
        self.assertEqual(list((self.repo / "ECO").glob("*.tmp")), [])

    def test_missing_or_mismatched_files(self):
        with self.assertRaises(eco_model.EcoError) as ctx:
            eco_store.load(self.repo, "ECO-0009")
        self.assertIn("Get Latest", str(ctx.exception))
        eco_store.save(self.repo, an_eco("ECO-0002"))
        os.replace(self.repo / "ECO" / "ECO-0002.yaml", self.repo / "ECO" / "ECO-0003.yaml")
        with self.assertRaises(eco_model.EcoError):
            eco_store.load(self.repo, "ECO-0003")


class TestLifecycle(RegistryTestCase):
    def setUp(self):
        super().setUp()
        self.make(1)
        self.make(2)
        self.pns = [PN("HCR", 1, 1), PN("HCR", 2, 1)]
        self.eco = eco_lifecycle.open_eco(self.repo, " Bracket ", "Why", "release", "T1", "abc123",
                                          [(pn, "A") for pn in self.pns], "Alex Smith")

    def wait_on(self, pn, request_id="abc123"):
        record = record_store.load(self.repo, pn)
        record.pending = {"id": request_id, "action": "release", "revision": "A", "requested_by": "Alex",
                          "template": {}, "signoffs": [], "slots": []}
        record_store.save(self.repo, record)

    def test_opening_writes_the_next_open_eco(self):
        self.assertEqual((self.eco.number, self.eco.name, self.eco.status), ("ECO-0001", "Bracket", eco_model.OPEN))
        self.assertEqual(self.eco.parts, [{"pn": "HCR-00001-001", "revision": "A"},
                                          {"pn": "HCR-00002-001", "revision": "A"}])
        self.assertEqual(self.eco.history[0]["event"], "opened")
        self.assertEqual(eco_store.load(self.repo, "ECO-0001"), self.eco)
        again = eco_lifecycle.open_eco(self.repo, "Next", "", "release", "T1", "def456", [], "Alex Smith")
        self.assertEqual(again.number, "ECO-0002")

    def test_it_stays_open_while_a_part_still_waits(self):
        self.wait_on(self.pns[1])
        self.assertIsNone(eco_lifecycle.close_if_done(self.repo, "ECO-0001", eco_model.RELEASED, "Bea"))
        self.assertEqual(eco_store.load(self.repo, "ECO-0001").status, eco_model.OPEN)
        self.wait_on(self.pns[1], "another")                           # in a different request now: not ours
        self.assertEqual(eco_lifecycle.close_if_done(self.repo, "ECO-0001", eco_model.RELEASED, "Bea"),
                         "ECO/ECO-0001.yaml")

    def test_closing_copies_the_sign_offs_and_notes_who(self):
        pending = {"id": "abc123", "signoffs": [{"id": "bea", "by": "Bea Jones"}]}
        eco_lifecycle.close_if_done(self.repo, "ECO-0001", eco_model.REJECTED, "Bea Jones", pending, "Too thin")
        eco = eco_store.load(self.repo, "ECO-0001")
        self.assertEqual((eco.status, eco.signoffs), (eco_model.REJECTED, [{"id": "bea", "by": "Bea Jones"}]))
        self.assertEqual({k: eco.history[-1][k] for k in ("event", "by", "comment")},
                         {"event": "rejected", "by": "Bea Jones", "comment": "Too thin"})

    def test_a_closed_eco_is_never_changed(self):
        eco_lifecycle.close_if_done(self.repo, "ECO-0001", eco_model.WITHDRAWN, "Alex Smith")
        with self.assertRaises(eco_model.EcoError) as ctx:
            eco_lifecycle.close_if_done(self.repo, "ECO-0001", eco_model.RELEASED, "Alex Smith")
        self.assertIn("withdrawn", str(ctx.exception))
        self.assertEqual(eco_store.load(self.repo, "ECO-0001").status, eco_model.WITHDRAWN)


class TestTemplates(unittest.TestCase):
    def test_require_eco_is_saved_only_when_on(self):
        rows = [workflow_templates.Row(["Quality"])]
        on = workflow_templates.Template(workflow_templates.RELEASE, "T1", rows, require_eco=True)
        off = workflow_templates.Template(workflow_templates.RELEASE, "T2", rows)
        self.assertTrue(on.to_dict()["require_eco"])
        self.assertNotIn("require_eco", off.to_dict())
        self.assertEqual(workflow_templates.Template.from_dict(workflow_templates.RELEASE, "T1", on.to_dict()), on)
        self.assertEqual(workflow_templates.Template.from_dict(workflow_templates.RELEASE, "T2", off.to_dict()), off)
        with self.assertRaises(workflow_templates.WorkflowError):
            workflow_templates.Template.from_dict(workflow_templates.RELEASE, "T1",
                                                  {"require_eco": "yes", "signoffs": [{"roles": ["Quality"]}]})

    def test_a_vault_using_ecos_needs_the_version_that_has_them(self):
        rows = [workflow_templates.Row(["Quality"])]
        plain = {workflow_templates.RELEASE: {"T2": workflow_templates.Template(workflow_templates.RELEASE, "T2", rows)}}
        eco = {workflow_templates.RELEASE: {"T1": workflow_templates.Template(workflow_templates.RELEASE, "T1", rows,
                                                                              require_eco=True)}}
        self.assertEqual(workflow_templates.min_version_for(plain, "0.4.0"), workflow_templates.MIN_VERSION)
        self.assertEqual(workflow_templates.min_version_for(eco, "0.4.0"), workflow_templates.ECO_MIN_VERSION)
        self.assertEqual(workflow_templates.min_version_for(eco, "0.3.2"), "0.3.2")    # never above the one running
