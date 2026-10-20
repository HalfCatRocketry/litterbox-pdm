"""Tests that Check Out is refused, leaving nothing locked, on a computer whose SolidWorks is newer than the org's.
They need Linux, macOS or WSL."""

import unittest
from tests.support.engine_fixture import EngineFixture
from tests.support.gui_fakes import replace
from tests.support.vault_fixture import PART, SKIP_ON_WINDOWS
from litterbox.cad.solidworks import sw_process
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkout
from litterbox.records import record_store
from litterbox.vault import config_write


@SKIP_ON_WINDOWS
class NewerSolidWorks(EngineFixture, unittest.TestCase):
    def test_check_out_is_refused_and_nothing_is_locked(self):
        config_write.set_values(self.a, solidworks_version=2024)
        replace(self, sw_process, "installed_major_version", lambda: 33)          # SolidWorks 2025
        with self.user("Alex"):
            with self.assertRaisesRegex(LitterboxError, "your SolidWorks is 2025"):
                checkout.checkout(self.a, PART)
            with self.assertRaisesRegex(LitterboxError, "check out these 2 parts"):
                checkout.checkout_many(self.a, [PART, PN("HCR", 2, 1)])
            self.assertEqual(self.locks(self.a), {})
        self.assertNotEqual(record_store.load(self.a, PART).history[-1]["event"], "checked_out")

    def test_the_orgs_own_version_checks_out_as_usual(self):
        config_write.set_values(self.a, solidworks_version=2024)
        replace(self, sw_process, "installed_major_version", lambda: 32)
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            self.assertEqual(self.status_of(self.a).kind, "mine")


if __name__ == "__main__":
    unittest.main()
