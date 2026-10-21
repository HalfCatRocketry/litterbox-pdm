"""Tests for BOM lines added by hand (parts/bom_items.py): which parts may be added, how they show in the BOM, where
used and the release checks, and adding them to a kit (a non-CAD assembly). The flow runs against real git repos
(a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so it needs Linux, macOS or WSL and is
skipped on Windows; the rest needs no git."""

import unittest
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.gui.logic import bom_text
from litterbox.parts import bom_items
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import create
from litterbox.parts import get_latest
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.references import bom
from litterbox.references import reference_model
from litterbox.references import reference_queries
from tests.support.create_fixture import CreateFixture
from tests.support.vault_fixture import SKIP_ON_WINDOWS

FRAME, BOLT, PAINT, KIT = PN("HCR", 1, 500), PN("HCR", 2, 1), PN("HCR", 3, 1), PN("HCR", 4, 500)


def make(pn, name, kind=record_model.KIND_CAD, released="A", **fields):
    return record_model.Record(pn=pn, name=name, created_by="Alex", created_at="t", released_revision=released,
                               kind=kind, **fields)


def records():
    frame = make(FRAME, "Frame", references={"A": ["HCR-00002-001_A"]}, quantities={"A": {"HCR-00002-001_A": 8}},
                 bom_items={"A": {"HCR-00003-001_A": 2}})
    kit = make(KIT, "Spares kit", record_model.KIND_NONCAD,
               bom_items={"A": {"HCR-00002-001_A": 20, "HCR-00003-001_A": 1}})
    return {FRAME: frame, BOLT: make(BOLT, "Bolt"), PAINT: make(PAINT, "Paint", record_model.KIND_NONCAD), KIT: kit}


class Lines(unittest.TestCase):
    def test_lines_added_by_hand_join_the_model_with_their_own_quantity(self):
        found = bom.lines(records(), FRAME, "A", bom.SINGLE)
        self.assertEqual([(line.pn, line.quantity, line.added) for line in found],
                         [(BOLT, 8, False), (PAINT, 2, True)])
        self.assertEqual(bom.problems(found), [])

    def test_a_kit_is_only_its_lines_and_counts_down_the_tree(self):
        self.assertEqual([(line.pn, line.total) for line in bom.lines(records(), KIT, "A", bom.FLAT)],
                         [(BOLT, 20), (PAINT, 1)])

    def test_where_used_and_uses_include_them(self):
        found = reference_queries.where_used(None, PAINT, records())
        self.assertEqual([(u.parent, u.added) for u in found], [(FRAME, True), (KIT, True)])
        uses = reference_queries.uses(None, FRAME, "A", records())
        self.assertFalse(next(u for u in uses if u.child == PAINT).replaceable)

    def test_the_tab_marks_them_and_lets_only_them_be_removed(self):
        found = bom.lines(records(), FRAME, "A", bom.SINGLE)
        self.assertEqual(bom_text.removable(found), {"line1": "HCR-00003-001_A"})
        self.assertTrue(bom_text.table(found, bom.SINGLE)[1][1][-1].endswith("(added by hand)"))


class Rules(unittest.TestCase):
    def test_a_cad_assembly_takes_only_non_cad_parts_and_a_kit_takes_any(self):
        r = records()
        self.assertEqual(bom_items.item_problem(r[FRAME], r[PAINT]), "")
        self.assertIn("CAD part", bom_items.item_problem(r[FRAME], r[BOLT]))
        self.assertEqual(bom_items.item_problem(r[KIT], r[BOLT]), "")
        self.assertIn("itself", bom_items.item_problem(r[KIT], r[KIT]))
        void = make(PN("HCR", 5, 1), "Old", status=record_model.STATUS_VOID)
        self.assertIn("void", bom_items.item_problem(r[KIT], void))

    def test_the_window_offers_the_same(self):
        row = lambda pn, noncad=False, kind="ok": SimpleNamespace(pn=pn, noncad=noncad, kind=kind)
        rows = [row(FRAME), row(BOLT), row(PAINT, True), row(KIT, True), row(PN("HCR", 5, 1), True, "void")]
        self.assertEqual([r.pn for r in bom_text.item_choices(rows, rows[0])], [PAINT, KIT])
        self.assertEqual([r.pn for r in bom_text.item_choices(rows, rows[3])], [FRAME, BOLT, PAINT])

    def test_a_line_is_added_changed_and_taken_off_in_the_history(self):
        r = make(KIT, "Kit", record_model.KIND_NONCAD, released="")
        record_lifecycle.set_bom_item(r, "Alex", "HCR-00002-001_A", 4)
        record_lifecycle.set_bom_item(r, "Alex", "HCR-00002-001_A", 6)
        self.assertIsNone(record_lifecycle.set_bom_item(r, "Alex", "HCR-00002-001_A", 6))
        record_lifecycle.set_bom_item(r, "Alex", "HCR-00002-001_A", None)
        self.assertEqual(r.bom_items, {})
        self.assertEqual([e["changes"][0] for e in r.history], ["BOM: HCR-00002-001_A x 4 added",
                                                                "BOM: HCR-00002-001_A x 6 (was 4)",
                                                                "BOM: removed HCR-00002-001_A"])
        self.assertEqual(bom_items.clean_quantity(" 3 "), 3)
        for bad in ("0", "two", "-1"):
            self.assertRaises(LitterboxError, bom_items.clean_quantity, bad)

    def test_they_are_written_and_read_back_and_carried_to_the_next_revision(self):
        r = records()[FRAME]
        r.status = record_model.STATUS_RELEASED
        self.assertEqual(record_model.Record.from_dict(r.to_dict()).bom_items, r.bom_items)
        from litterbox.records import record_revisions
        record_revisions.mark_revised(r, "Alex", "Next", [])
        self.assertEqual(r.bom_items["B"], {"HCR-00003-001_A": 2})


@SKIP_ON_WINDOWS
class KitFlow(CreateFixture, unittest.TestCase):
    def test_a_kit_is_built_in_its_bom_and_checked_in(self):
        with self.user("Alex"):
            paint = create.new_part(self.a, "Paint", noncad=True)
            kit = create.new_part(self.a, "Spares kit", kind=create.ASSEMBLY, noncad=True)
            self.assertEqual(kit.variant, 500)
            with self.assertRaisesRegex(LitterboxError, "checked out"):
                bom_items.set_item(self.a, kit, paint, 2)
            checkout.checkout(self.a, kit)
            self.assertEqual(bom_items.set_item(self.a, kit, paint, 2), f"{paint}_A")
            self.assertEqual(bom_items.set_item(self.a, kit, PN("HCR", 1, 1), "4"), "HCR-00001-001_A")   # a CAD part
            bom_items.remove_item(self.a, kit, f"{paint}_A")
            checkin.checkin(self.a, kit, "Spares")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            found = bom.lines(reference_model.load_records(self.b), kit, "A", bom.SINGLE)
            self.assertEqual([(str(line.pn), line.quantity) for line in found], [("HCR-00001-001", 4)])


if __name__ == "__main__":
    unittest.main()
