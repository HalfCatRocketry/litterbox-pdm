"""Tests for New Assembly's variants (from 500, or the org's choice) against real git repos, and an Admin changing
where they start. Alex is the Owner; Bea is a Member. The vault has part HCR-00001-001. They need Linux, macOS or WSL
and are skipped on Windows."""

import unittest

from tests.support.vault_fixture import SKIP_ON_WINDOWS
from tests.support.workflow_fixture import Fixture

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import create
from litterbox.parts import number_suggestions
from litterbox.vault import config
from litterbox.vault import settings_admin


@SKIP_ON_WINDOWS
class AssemblyVariants(Fixture, unittest.TestCase):
    def test_a_new_assembly_starts_at_500_and_a_new_part_below_it(self):
        with self.user("Alex"):
            assembly = create.new_part(self.a, "Gearbox", kind=create.ASSEMBLY)
            self.assertEqual(assembly, PN("HCR", 2, 500))
            self.assertEqual(create.new_part(self.a, "Gearbox, wide", base=2, kind=create.ASSEMBLY), PN("HCR", 2, 501))
            self.assertEqual(create.new_part(self.a, "Gear", base=2), PN("HCR", 2, 1))
            self.assertEqual(create.new_part(self.a, "Shaft"), PN("HCR", 3, 1))
            self.assertEqual(create.new_part(self.a, "Typed by hand", base=3, variant=2, kind=create.ASSEMBLY),
                             PN("HCR", 3, 2))                   # allowed: the window only warns

    def test_the_dialogs_suggestions_follow_the_kind(self):
        with self.user("Alex"):
            self.assertEqual(number_suggestions.suggest_numbers(self.a, kind=create.ASSEMBLY), (2, 500))
            self.assertEqual(number_suggestions.suggest_numbers(self.a, 1, kind=create.ASSEMBLY), (1, 500))
            self.assertEqual(number_suggestions.suggest_numbers(self.a, 1), (1, 2))
            self.assertEqual(number_suggestions.check_numbers(self.a, 1, None, kind=create.ASSEMBLY).pn,
                             PN("HCR", 1, 500))
            self.assertEqual(create.variant_range(self.a, create.ASSEMBLY), (500, 999))
            self.assertEqual(create.variant_range(self.a), (1, 499))

    def test_an_admin_moves_the_start_for_everyone(self):
        with self.user("Alex"):
            self.assertTrue(settings_admin.edit(self.a, assembly_variant_start=700))
        self.assertIn("Vault settings: assembly_variant_start = 700", self.remote_log()[0])
        self.get_latest("Bea")
        self.assertEqual(config.get_assembly_variant_start(self.b), 700)
        with self.user("Bea"):
            self.assertEqual(create.new_part(self.b, "Frame", kind=create.ASSEMBLY), PN("HCR", 2, 700))
            with self.assertRaises(LitterboxError):
                settings_admin.edit(self.b, assembly_variant_start=600)
            with self.assertRaises(LitterboxError):
                settings_admin.edit(self.b, assembly_variant_start=0)

    def test_a_kind_with_no_variants_left_says_so(self):
        with self.user("Alex"):
            settings_admin.edit(self.a, assembly_variant_start=998)
            create.new_part(self.a, "A", kind=create.ASSEMBLY)
            create.new_part(self.a, "B", base=2, kind=create.ASSEMBLY)
            with self.assertRaises(LitterboxError) as caught:
                create.new_part(self.a, "C", base=2, kind=create.ASSEMBLY)
        self.assertIn("Every assembly variant of part number 00002 (998 to 999) is used", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
