"""Tests for vault/record_upgrade.py (Vault > Upgrade records...): which records are old and what an upgrade would
do, on the old records in tests/records/fixtures/ (no git); then upgrading for real, against real git repos (a bare
remote plus a clone each for Alex and Bea) with a fake git-lfs, so those need Linux, macOS or WSL."""

import unittest

import yaml

from litterbox import layout
from litterbox.core import doc_number
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import lfs_locks
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.vault import config
from litterbox.vault import record_upgrade
from tests.support import record_fixtures
from tests.support.gui_fakes import replace
from tests.support.registry_case import RegistryTestCase
from tests.support.vault_fixture import PART, REC, SKIP_ON_WINDOWS, TwoUserVault, is_writable

ALL = {PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 500), PN("HCR", 4, 500), PN("HCR", 5, 1)}


class FindingOldRecords(RegistryTestCase):
    def setUp(self):
        super().setUp()
        record_fixtures.use_five_digits(self)
        record_fixtures.copy_into(self.repo)
        replace(self, lfs_locks, "get_locks", lambda repo, strict=False: {})

    def set_minimum(self, minimum):
        path = self.repo / layout.CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"min_litterbox_version": minimum}), encoding="utf-8")

    def test_without_steps_nothing_is_old_and_nothing_is_read(self):
        record_fixtures.pretend_steps(self, steps={})
        replace(self, record_store, "list_pns", lambda *a, **k: self.fail("no need to look"))
        self.assertEqual(record_upgrade.outdated(self.repo), {})
        self.assertFalse(record_upgrade.needs_upgrade(self.repo))

    def test_every_old_record_is_found_with_its_format_and_a_broken_one_is_left_out(self):
        record_fixtures.pretend_steps(self)
        (self.repo / "PN-logs" / "HCR-00009-001.yaml").write_text("pn: [unclosed\n", encoding="utf-8")
        found = record_upgrade.outdated(self.repo)
        self.assertEqual(set(found), ALL | {doc_number.parse("PROP-0001")})
        self.assertTrue(all(fmt == 1 for fmt in found.values()))
        self.assertTrue(record_upgrade.needs_upgrade(self.repo))

    def test_the_plan_counts_each_step_and_names_the_checked_out_records(self):
        record_fixtures.pretend_steps(self)
        replace(self, lfs_locks, "get_locks",
                lambda repo, strict=False: {"pn-logs/hcr-00003-500.yaml": ("other", "Bea Jones")})
        plan = record_upgrade.plan(self.repo)
        self.assertEqual(len(plan.outdated), 6)
        self.assertEqual(plan.steps, [(record_fixtures.STEP_1, 6), (record_fixtures.STEP_2, 6)])
        self.assertEqual(plan.checked_out, [PN("HCR", 3, 500)])
        self.assertEqual(plan.raise_minimum, "0.5.0")

    def test_a_vault_that_requires_the_version_already_is_not_raised_again(self):
        record_fixtures.pretend_steps(self)
        self.set_minimum("0.5.5")
        self.assertEqual(record_upgrade.plan(self.repo).raise_minimum, "")
        self.set_minimum("0.4.2")
        self.assertEqual(record_upgrade.plan(self.repo).raise_minimum, "0.5.0")

    def test_a_vault_whose_records_are_new_but_cannot_be_written_yet_still_needs_it(self):
        record_fixtures.pretend_steps(self)
        for path in self.repo.rglob("*.yaml"):
            if "logs" in path.parent.name.lower():
                path.write_text(path.read_text(encoding="utf-8").replace("format: 1\n", "format: 3\n"),
                                encoding="utf-8")
        self.assertEqual(set(record_upgrade.outdated(self.repo)), {PN("HCR", 1, 1)})     # it has no format line
        (self.repo / "PN-logs" / "HCR-00001-001.yaml").unlink()
        self.assertEqual(record_upgrade.outdated(self.repo), {})
        self.assertTrue(record_upgrade.needs_upgrade(self.repo))          # nothing old, but writing isn't allowed
        record_fixtures.vault_requires("0.5.0")
        self.assertFalse(record_upgrade.needs_upgrade(self.repo))


@SKIP_ON_WINDOWS
class UpgradingAVault(TwoUserVault, unittest.TestCase):
    def record_text(self, repo):
        return (repo / REC).read_text(encoding="utf-8")

    def test_an_admin_upgrades_every_record_for_everyone(self):
        record_fixtures.pretend_steps(self)
        with self.user("Alex"):
            result = record_upgrade.upgrade(self.a)
            self.assertEqual((result.rewritten, result.checked_out, result.errors), (1, [], {}))
            self.assertTrue(self.record_text(self.a).startswith("format: 3\n"))
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / REC))
        log = self.remote_log()
        self.assertEqual(log[:2], ["HCR-00001-001: Record upgraded to format 3",
                                   "Vault needs Litterbox 0.5.0: records in format 3"])
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue(self.record_text(self.b).startswith("format: 3\n"))
            self.assertEqual(config.load(self.b)["min_litterbox_version"], "0.5.0")
            checkout.checkout(self.b, PART)                         # Bea may change things again
            checkin.checkin(self.b, PART, "After the upgrade", allow_unchanged=True)

    def test_running_it_again_changes_nothing(self):
        record_fixtures.pretend_steps(self)
        with self.user("Alex"):
            record_upgrade.upgrade(self.a)
            log = self.remote_log()
            self.assertEqual(record_upgrade.upgrade(self.a), record_upgrade.Result())
        self.assertEqual(self.remote_log(), log)

    def test_before_the_upgrade_nothing_can_be_changed_and_nothing_is_left_half_done(self):
        record_fixtures.pretend_steps(self)
        log = self.remote_log()
        with self.user("Bea"):
            with self.assertRaisesRegex((LitterboxError, record_model.RegistryError), "Upgrade records"):
                checkout.checkout(self.b, PART)
            self.assertEqual(self.locks(self.b), {})
        self.assertEqual(self.remote_log(), log)

    def test_a_checked_out_record_is_left_until_it_is_checked_in(self):
        with self.user("Bea"):
            checkout.checkout(self.b, PART)
        record_fixtures.pretend_steps(self)
        with self.user("Alex"):
            result = record_upgrade.upgrade(self.a)
        self.assertEqual((result.rewritten, result.checked_out), (0, [PART]))
        self.assertEqual(self.remote_log()[0], "Vault needs Litterbox 0.5.0: records in format 3")
        with self.user("Bea"):                         # her copy hasn't seen the upgrade: the check-in fetches it
            checkin.checkin(self.b, PART, "Checked in after the upgrade", allow_unchanged=True)
            self.assertTrue(self.record_text(self.b).startswith("format: 3\n"))
        with self.user("Alex"):
            get_latest.get_latest(self.a)
            self.assertEqual(record_upgrade.outdated(self.a), {})


if __name__ == "__main__":
    unittest.main()
