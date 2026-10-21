"""Tests for non-CAD parts: creating one, its kind, and check out, check in, release, revise, cancel and void with no
files. The flows run against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs,
so they need Linux, macOS or WSL and are skipped on Windows; the rules need no git."""

import unittest
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import confirmations
from litterbox.parts import cancel_revision
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import create
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import part_details
from litterbox.parts import planning
from litterbox.parts import revise
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config
from tests.support.create_fixture import CreateFixture
from tests.support.vault_fixture import PART, SKIP_ON_WINDOWS

NONCAD, CAD = record_model.KIND_NONCAD, record_model.KIND_CAD


def record(kind=NONCAD):
    return record_model.Record(PN("HCR", 9, 1), "Paint, black", "Alex", "2026-10-21T10:00:00Z", kind=kind)


class Rules(unittest.TestCase):
    def test_the_kind_is_written_only_for_non_cad_parts(self):
        self.assertEqual(record_model.Record.from_dict(record().to_dict()).kind, NONCAD)
        self.assertNotIn("kind", record(CAD).to_dict())
        self.assertEqual(record_model.Record.from_dict(record(CAD).to_dict()).kind, CAD)
        data = record().to_dict()
        data["kind"] = "hologram"
        with self.assertRaisesRegex(record_model.RegistryError, "Update Litterbox"):
            record_model.Record.from_dict(data)

    def test_the_kind_changes_only_before_release_and_without_solidworks_files(self):
        r = record(CAD)
        entry = record_lifecycle.change_kind(r, "Alex", NONCAD, has_cad_files=False)
        self.assertEqual((r.kind, entry["changes"]), (NONCAD, ["kind: CAD -> Non-CAD"]))
        self.assertIsNone(record_lifecycle.change_kind(r, "Alex", NONCAD, has_cad_files=False))
        with self.assertRaisesRegex(record_model.RegistryError, "SolidWorks files"):
            record_lifecycle.change_kind(record(CAD), "Alex", NONCAD, has_cad_files=True)
        released = record()
        record_lifecycle.mark_released(released, "Alex", [])
        with self.assertRaisesRegex(record_model.RegistryError, "released"):
            record_lifecycle.change_kind(released, "Alex", CAD, has_cad_files=False)

    def test_the_window_says_why_the_kind_is_fixed(self):
        row = SimpleNamespace(released_revision="", record_status="in_work", cots=False, revisions={})
        self.assertEqual(confirmations.kind_note(row), "")
        row.revisions = {"A": ["cad/HCR-00009-001_A.SLDPRT"]}
        self.assertIn("SolidWorks files", confirmations.kind_note(row))
        row.released_revision = "A"
        self.assertIn("released", confirmations.kind_note(row))

    def test_cad_only_actions_are_greyed_out(self):
        pn = PN("HCR", 9, 1)
        rows = {pn: SimpleNamespace(pn=pn, kind="ok", state="Available (non-CAD)", noncad=True)}
        for action in ("open", "open_drawing", "generate_step_pdf", "make_cots"):
            self.assertIn("non-CAD", action_rules.plan_action(action, [pn], rows).message)
        self.assertEqual(action_rules.plan_action("release", [pn], rows).targets, [pn])
        self.assertEqual(action_rules.plan_action("checkout", [pn], rows).targets, [pn])


@SKIP_ON_WINDOWS
class NonCadFlow(CreateFixture, unittest.TestCase):
    def test_the_first_non_cad_part_makes_the_vault_need_this_litterbox(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Paint, black", noncad=True)
            self.assertEqual(record_store.load(self.a, pn).kind, NONCAD)
            self.assertEqual(config.load(self.a)["min_litterbox_version"], create.NONCAD_MIN_VERSION)
            self.assertEqual(self.status_of(self.a, pn).state, "Available (non-CAD)")
            self.assert_clean(self.a)
            create.new_part(self.a, "Paint, white", noncad=True)        # already raised: nothing more to change
            self.assert_clean(self.a)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue(self.status_of(self.b, pn).noncad)

    def test_a_non_cad_part_goes_through_its_whole_life_without_files(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Loctite 243", noncad=True)
            checkout.checkout(self.a, pn)
            part_details.edit_details(self.a, pn, "Loctite 243, 10 ml", "")
            checkin.checkin(self.a, pn, "Named the size", allow_unchanged=True)
            self.assertTrue(planning.release_plan(self.a, pn).ok)
            lifecycle.release(self.a, pn)
            self.assertEqual(revise.revise(self.a, pn, "New supplier", backend=object(), log=lambda *_: None), [])
            record = record_store.load(self.a, pn)
            self.assertEqual((record.revision, record.status), ("B", "in_work"))
            checkin.checkin(self.a, pn, "Nothing to change", allow_unchanged=True)
            cancel_revision.cancel_revision(self.a, pn, "Not needed", backend=object(), log=lambda *_: None)
            self.assertEqual(record_store.load(self.a, pn).revision, "A")
            self.assertIn("non-CAD", planning.make_cots_plan(self.a, create.new_part(self.a, "Glue", noncad=True)).problems[0])

    def test_a_cad_part_with_files_keeps_its_kind(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            with self.assertRaisesRegex(LitterboxError, "SolidWorks files"):
                part_details.edit_details(self.a, PART, "Front upright", "", kind=NONCAD)
            pn = create.new_part(self.a, "Not modeled after all")
            checkout.checkout(self.a, pn)
            self.assertTrue(part_details.edit_details(self.a, pn, "Not modeled after all", "", kind=NONCAD))
            self.assertEqual(record_store.load(self.a, pn).kind, NONCAD)


if __name__ == "__main__":
    unittest.main()
