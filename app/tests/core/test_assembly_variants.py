"""Tests for the variant assemblies start at (config, numbering, Create new org's words) and the Break Checkout
rules and words. None of these need git; the real flows are in tests/parts/test_assembly_variants.py and
tests/parts/test_break_checkout.py."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core import numbering
from litterbox.core import part_number
from litterbox.core.part_number import PN
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import checkin_text
from litterbox.gui.logic import history_text
from litterbox.gui.logic import org_menu
from litterbox.records import record_model
from litterbox.team import team_model
from litterbox.vault import config
from litterbox.vault import config_write
from litterbox.vault import create_vault


class AssemblyVariantSetting(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        self.addCleanup(part_number.configure)

    def write(self, text):
        path = config.config_path(self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("org: HCR\n" + text, encoding="utf-8")

    def test_the_default_is_five_followed_by_zeros(self):
        self.write("")
        self.assertEqual(config.get_assembly_variant_start(self.repo), 500)
        self.write("pn_variant_digits: 2\n")
        self.assertEqual(config.get_assembly_variant_start(self.repo), 50)
        self.assertEqual(config.default_assembly_variant(1), 5)

    def test_it_can_be_set_and_must_leave_room_on_both_sides(self):
        self.write("")
        config_write.set_values(self.repo, assembly_variant_start=600)
        self.assertEqual(config.get_assembly_variant_start(self.repo), 600)
        for bad in (1, 1000, "500", True):
            with self.assertRaises(config.ConfigError):
                config_write.set_values(self.repo, assembly_variant_start=bad)
        self.write("assembly_variant_start: 0\n")
        with self.assertRaises(config.ConfigError) as caught:
            config.get_assembly_variant_start(self.repo)
        self.assertIn("assembly_variant_start", str(caught.exception))

    def test_a_new_vault_checks_it_against_its_variant_digits(self):
        self.assertTrue(create_vault.check_settings("HCR", 1, 5, 3, 500).ok)
        self.assertTrue(create_vault.check_settings("HCR", 1, 5, 3).ok)                 # None: the default
        self.assertFalse(create_vault.check_settings("HCR", 1, 5, 2, 500).ok)           # 2 digits only reach 99
        text = org_menu.fixed_settings_text("HCR", "", 1, 5, 3, assembly_variant=500)
        self.assertIn("Assembly variant number start:  500 (an Admin can change this later)", text)

    def test_the_next_variant_stays_in_its_range(self):
        self.assertEqual(numbering.next_variant({1, 2}), 3)
        self.assertEqual(numbering.next_variant({1, 2}, 500, 999), 500)
        self.assertEqual(numbering.next_variant({500}, 500, 999), 501)
        with self.assertRaises(part_number.PNError):
            numbering.next_variant(set(range(1, 500)), 1, 499)


class BreakCheckoutRules(unittest.TestCase):
    def row(self, kind):
        return SimpleNamespace(kind=kind, state=f"state {kind}", locked_by="bea")

    def test_only_a_part_someone_else_has_checked_out_can_be_broken(self):
        pn = PN("HCR", 1, 1)
        for kind, usable in (("theirs", True), ("mine", False), ("ok", False), ("released", False)):
            self.assertEqual(action_rules.action_available("break_checkout", [pn], [], {pn: self.row(kind)}),
                             usable, kind)
        self.assertIn("Tick just one part", action_rules.why_not(
            "break_checkout", [pn, PN("HCR", 2, 1)], [], {pn: self.row("theirs"), PN("HCR", 2, 1): self.row("theirs")}))

    def test_it_is_an_admin_action_and_its_history_says_whose_it_was(self):
        self.assertIn("break_checkout", team_model.ADMIN_ACTIONS)
        record = record_model.Record(PN("HCR", 1, 1), "Bracket", "alex", "2026-10-18T10:00:00Z", history=[
            {"event": "checkout_broken", "by": "alex", "at": "2026-10-18T10:00:00Z", "of": "bea",
             "reason": "Bea is away"}])
        _when, who, what, details = history_text.format_history(record, local=False)[0]
        self.assertEqual((who, what), ("alex", "Checkout broken"))
        self.assertIn("was checked out by bea", details)
        self.assertIn("Bea is away", details)

    def test_the_lifecycle_menu_has_it_only_for_those_who_may(self):
        from tests.support.gui_source import gui_source
        source = gui_source()
        self.assertIn('ADMIN_LIFECYCLE_MENU = (None, ("Break Checkout", "break_checkout"))', source)
        self.assertIn('self.identity.allows("break_checkout")[0]', source)
        self.assertIn("def break_checkout(self):", source)
        self.assertIn('("New Assembly", "new_assembly")', source)

    def test_the_words(self):
        self.assertIn("Break bea's checkout of HCR-00001-001?", checkin_text.break_checkout_prompt("HCR-00001-001", "bea"))
        text = checkin_text.recovered_text(Path("C:/Litterbox/v-recovered/now"), ["cad/HCR-00001-001_A.SLDPRT"])
        self.assertIn("HCR-00001-001_A.SLDPRT", text)
        self.assertIn("v-recovered", text)


if __name__ == "__main__":
    unittest.main()
