"""Tests for Purchasing Info (parts/purchasing.py) against real git repos (a bare remote plus a clone each for Alex
and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest

from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import purchasing
from litterbox.records import record_store
from tests.support.engine_fixture import EngineFixture
from tests.support.vault_fixture import PART, REC, SKIP_ON_WINDOWS, is_writable

ACME = {"supplier": "Acme", "unit_cost": "2.50", "lead_time_days": "10"}


@SKIP_ON_WINDOWS
class PurchasingFlow(EngineFixture, unittest.TestCase):
    def test_a_part_nobody_has_checked_out_is_changed_in_the_vault_at_once(self):
        with self.user("Alex"):
            self.assertEqual(purchasing.edit_purchasing(self.a, PART, ACME), purchasing.UPLOADED)
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / REC))
            self.assertIn("HCR-00001-001: Purchasing info changed", self.remote_log())
            self.assertEqual(purchasing.edit_purchasing(self.a, PART, {"supplier": "Acme"}), purchasing.UNCHANGED)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            record = record_store.load(self.b, PART)
            self.assertEqual(record.purchasing, {"supplier": "Acme", "unit_cost": "2.50", "lead_time_days": 10})
            self.assertEqual(record.history[-1]["event"], "purchasing_edited")

    def test_a_released_part_takes_it_without_a_revision(self):
        with self.user("Alex"):
            lifecycle.release(self.a, PART)
            self.assertEqual(purchasing.edit_purchasing(self.a, PART, ACME), purchasing.UPLOADED)
            record = record_store.load(self.a, PART)
            self.assertEqual((record.status, record.revision, record.purchasing["supplier"]),
                             ("released", "A", "Acme"))

    def test_your_own_checkout_keeps_it_until_you_check_in(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            log_before = self.remote_log()
            self.assertEqual(purchasing.edit_purchasing(self.a, PART, ACME), purchasing.SAVED_LOCALLY)
            self.assertEqual(self.remote_log(), log_before)          # nothing uploaded yet
            self.assertIn(REC.lower(), self.locks(self.a))           # still checked out
            checkin.checkin(self.a, PART, "Bought in")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(record_store.load(self.b, PART).purchasing["unit_cost"], "2.50")

    def test_someone_elses_checkout_makes_it_wait(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            with self.assertRaisesRegex(LitterboxError, "checked out by"):
                purchasing.edit_purchasing(self.b, PART, ACME)
            self.assertEqual(record_store.load(self.b, PART).purchasing, {})

    def test_a_bad_value_changes_nothing(self):
        with self.user("Alex"):
            log_before = self.remote_log()
            with self.assertRaisesRegex(LitterboxError, "Unit cost"):
                purchasing.edit_purchasing(self.a, PART, {"unit_cost": "lots"})
            self.assertEqual((self.remote_log(), self.locks(self.a)), (log_before, {}))


if __name__ == "__main__":
    unittest.main()
