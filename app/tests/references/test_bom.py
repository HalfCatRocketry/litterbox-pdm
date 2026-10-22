"""Tests for working out a BOM from the parts each assembly revision uses. No git: the records are made in memory."""

import unittest

from litterbox.core.part_number import PN
from litterbox.records import record_model
from litterbox.references import bom
from litterbox.references import reference_model

TOP, FRAME, BRACKET, BOLT, PANEL = (PN("HCR", n, 1) for n in (1, 2, 3, 4, 5))


def make(pn, name, references=None, released="A", **fields):
    return record_model.Record(pn=pn, name=name, created_by="Alex", created_at="t", released_revision=released,
                               status=record_model.STATUS_RELEASED if released else record_model.STATUS_IN_WORK,
                               references=references or {}, **fields)


def vault():
    """Top uses Frame and Panel; Frame uses Bracket and Bolt; Panel uses Bolt too."""
    return {
        TOP: make(TOP, "Top", {"A": ["HCR-00002-001_A", "HCR-00005-001_A"]}),
        FRAME: make(FRAME, "Frame", {"A": ["HCR-00003-001_A", "HCR-00004-001_A"]}),
        BRACKET: make(BRACKET, "Bracket"),
        BOLT: make(BOLT, "Bolt", cots=True, purchasing={"supplier": "Acme", "unit_cost": "0.10"}),
        PANEL: make(PANEL, "Panel", {"A": ["HCR-00004-001_A"]}),
    }


def listed(lines):
    return [(line.level, line.pn.base, line.revision) for line in lines]


class Modes(unittest.TestCase):
    def test_single_level_is_what_the_assembly_itself_uses(self):
        self.assertEqual(listed(bom.lines(vault(), TOP, "A", bom.SINGLE)), [(1, 2, "A"), (1, 5, "A")])

    def test_indented_puts_what_each_sub_assembly_uses_under_it(self):
        self.assertEqual(listed(bom.lines(vault(), TOP, "A", bom.INDENTED)),
                         [(1, 2, "A"), (2, 3, "A"), (2, 4, "A"), (1, 5, "A"), (2, 4, "A")])

    def test_every_part_once_lists_each_part_revision_once(self):
        self.assertEqual(listed(bom.lines(vault(), TOP, "A", bom.FLAT)),
                         [(0, 2, "A"), (0, 3, "A"), (0, 4, "A"), (0, 5, "A")])

    def test_a_part_that_is_not_an_assembly_has_an_empty_bom(self):
        self.assertEqual(bom.lines(vault(), BOLT, "A"), [])
        with self.assertRaises(ValueError):
            bom.lines(vault(), TOP, "A", "sideways")

    def test_each_line_carries_the_part_and_its_purchasing(self):
        bolt = [line for line in bom.lines(vault(), FRAME, "A") if line.pn == BOLT][0]
        self.assertEqual((bolt.name, bolt.cots, bolt.field("supplier"), bolt.field("unit_cost")),
                         ("Bolt", True, "Acme", "0.10"))
        self.assertEqual(bolt.field("lead_time_days"), "")
        frame = bom.lines(vault(), TOP, "A", bom.SINGLE)[0]
        self.assertTrue(frame.sub_assembly)


class Problems(unittest.TestCase):
    def test_a_missing_part_and_an_unreleased_one_are_flagged(self):
        records = vault()
        records[FRAME].references["A"].append("HCR-00009-001_A")
        records[BRACKET] = make(BRACKET, "Bracket", released="")
        found = bom.lines(records, FRAME, "A", bom.SINGLE)
        states = {line.pn.base: line.state for line in found}
        self.assertEqual(states, {3: reference_model.UNRELEASED, 4: reference_model.OK, 9: reference_model.MISSING})
        self.assertEqual(bom.problems(found), ["1 line: part not found", "1 line: not released",
                                               "3 lines: quantity not known"])

    def test_a_loop_stops_instead_of_going_round_for_ever(self):
        records = vault()
        records[BRACKET] = make(BRACKET, "Bracket", {"A": ["HCR-00001-001_A"]})       # Bracket uses Top
        found = bom.lines(records, TOP, "A", bom.INDENTED)
        looped = [line for line in found if line.loop]
        self.assertEqual(listed(looped), [(3, 1, "A")])
        self.assertIn("so the tree stops there", bom.problems(found)[-1])
        self.assertEqual(len(bom.lines(records, TOP, "A", bom.FLAT)), 5)

    def test_works_with_records_read_as_they_are_needed(self):
        records = vault()

        class Lazy:
            def get(self, pn, default=None):
                return records.get(pn, default)
        self.assertEqual(listed(bom.lines(Lazy(), TOP, "A", bom.SINGLE)), [(1, 2, "A"), (1, 5, "A")])


def counted():
    """vault(), with counts: Top uses 2 Frames and 1 Panel; a Frame uses 4 Brackets and 6 Bolts; a Panel 8 Bolts."""
    records = vault()
    records[TOP].quantities = {"A": {"HCR-00002-001_A": 2, "HCR-00005-001_A": 1}}
    records[FRAME].quantities = {"A": {"HCR-00003-001_A": 4, "HCR-00004-001_A": 6}}
    records[PANEL].quantities = {"A": {"HCR-00004-001_A": 8}}
    return records


def amounts(lines):
    return [(line.pn.base, line.quantity, line.total) for line in lines]


class Quantities(unittest.TestCase):
    def test_single_level_shows_how_many_the_assembly_uses(self):
        self.assertEqual(amounts(bom.lines(counted(), TOP, "A", bom.SINGLE)), [(2, 2, 2), (5, 1, 1)])

    def test_indented_multiplies_down_the_tree(self):
        self.assertEqual(amounts(bom.lines(counted(), TOP, "A", bom.INDENTED)),
                         [(2, 2, 2), (3, 4, 8), (4, 6, 12), (5, 1, 1), (4, 8, 8)])

    def test_every_part_once_adds_up_each_place_it_is_used(self):
        self.assertEqual(amounts(bom.lines(counted(), TOP, "A", bom.FLAT)),
                         [(2, 2, 2), (3, 8, 8), (4, 20, 20), (5, 1, 1)])

    def test_an_assembly_never_counted_leaves_its_lines_and_those_below_unknown(self):
        records = counted()
        records[FRAME].quantities = {}
        self.assertEqual(amounts(bom.lines(records, TOP, "A", bom.INDENTED)),
                         [(2, 2, 2), (3, None, None), (4, None, None), (5, 1, 1), (4, 8, 8)])
        self.assertEqual(amounts(bom.lines(records, TOP, "A", bom.FLAT))[2], (4, None, None))
        records[TOP].quantities = {}
        self.assertEqual(amounts(bom.lines(records, TOP, "A", bom.INDENTED))[4], (4, 8, None))
        self.assertIn("4 lines: quantity not known", bom.problems(bom.lines(records, TOP, "A", bom.INDENTED)))

    def test_a_part_with_every_copy_suppressed_counts_zero(self):
        records = counted()
        records[PANEL].quantities = {"A": {"HCR-00004-001_A": 0}}
        self.assertEqual(amounts(bom.lines(records, TOP, "A", bom.FLAT))[2], (4, 12, 12))


class Costs(unittest.TestCase):
    def test_the_total_is_every_part_revision_once_times_its_total_count(self):
        from decimal import Decimal
        from litterbox.gui.logic import bom_text
        records = counted()
        records[BRACKET].purchasing = {"unit_cost": "2.50"}
        summary = bom.cost_summary(records, TOP, "A")                 # 20 bolts at 0.10, 8 brackets at 2.50
        self.assertEqual((summary.total, summary.priced, summary.no_cost, summary.no_quantity),
                         (Decimal("22.00"), 2, 0, 0))                 # Frame and Panel are assemblies: not missing
        self.assertEqual([bom.line_cost(line) for line in bom.lines(records, TOP, "A", bom.INDENTED)],
                         [None, Decimal("20.00"), Decimal("1.20"), None, Decimal("0.80")])
        self.assertEqual(bom_text.cost_text(summary), "total cost 22.00")
        records[BRACKET].purchasing = {}
        records[PANEL].quantities = {}
        self.assertEqual(bom_text.cost_text(bom.cost_summary(records, TOP, "A")),
                         "total cost 0.00 (1 part has no unit cost, 1 is not counted)")
        self.assertEqual(bom_text.cost_text(bom.cost_summary(vault(), BRACKET, "A")), "")


if __name__ == "__main__":
    unittest.main()
