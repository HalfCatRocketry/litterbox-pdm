"""Tests for records/record_migrations.py: reading old records in the current shape, the steps on every old record
in tests/records/fixtures/, and writing records only in a vault that requires a Litterbox reading their format."""

import copy
import unittest

from litterbox import version
from litterbox.core.part_number import PN
from litterbox.records import record_migrations
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.records.record_model import RegistryError
from tests.support import record_fixtures
from tests.support.registry_case import RegistryTestCase


def load(data):
    return record_model.Record.from_dict(data)


class TheRealSteps(unittest.TestCase):
    """Whatever steps this Litterbox has: these hold for each of them."""

    def test_formats_have_no_gaps_and_the_current_one_follows_the_last(self):
        self.assertEqual(sorted(record_migrations.STEPS), list(range(1, record_migrations.current_format())))

    def test_each_step_says_what_changes_and_which_version_brought_it(self):
        since = [record_migrations.STEPS[n].since for n in sorted(record_migrations.STEPS)]
        for step in record_migrations.STEPS.values():
            self.assertTrue(step.what.strip())
            version.parse(step.since)
            self.assertFalse(version.is_newer(step.since, version.VERSION), "a step can't come from a later version")
        self.assertEqual(since, sorted(since, key=version.parse))

    def test_every_step_on_every_old_record_keeps_unknown_fields_and_can_run_twice(self):
        record_fixtures.use_five_digits(self)
        for name, data in record_fixtures.fixture_data().items():
            data = dict(data, zz_unknown={"kept": True})
            for old in sorted(record_migrations.STEPS):
                with self.subTest(record=name, step=old):
                    once = record_migrations.STEPS[old].change(copy.deepcopy(data))
                    twice = record_migrations.STEPS[old].change(copy.deepcopy(once))
                    self.assertEqual(once, twice)
                    self.assertEqual(once.get("zz_unknown"), {"kept": True})
                    data = dict(once, format=old + 1)
            load(record_migrations.upgrade(data))

    def test_without_steps_records_are_read_as_they_are_and_may_always_be_written(self):
        record_fixtures.pretend_steps(self, steps={})
        data = record_fixtures.fixture_data()["HCR-00002-001.yaml"]
        self.assertIs(record_migrations.upgrade(data), data)               # nothing copied on every refresh
        self.assertEqual(record_migrations.writes_need(), "")
        self.assertTrue(record_migrations.may_write())


class OldRecordsAreReadToday(unittest.TestCase):
    def setUp(self):
        record_fixtures.use_five_digits(self)

    def test_every_fixture_loads_and_writes_back_the_same(self):
        for name, data in record_fixtures.fixture_data().items():
            with self.subTest(record=name):
                record = load(data)
                again = load(record.to_dict())
                self.assertEqual(again, record)
                self.assertEqual(again.to_dict(), record.to_dict())
                self.assertEqual(record.to_dict()["format"], record_migrations.current_format())

    def test_the_oldest_record_gets_a_name_and_a_format(self):
        record = load(record_fixtures.fixture_data()["HCR-00001-001.yaml"])
        self.assertEqual((record.name, record.description), ("Bracket from before parts had names", ""))

    def test_a_field_no_litterbox_knows_is_kept(self):
        record = load(record_fixtures.fixture_data()["HCR-00002-001.yaml"])
        self.assertIn("kept by every Litterbox", record.to_dict()["custom_note"])


class WithSteps(unittest.TestCase):
    def setUp(self):
        record_fixtures.use_five_digits(self)
        record_fixtures.pretend_steps(self)
        self.data = record_fixtures.fixture_data()

    def test_an_old_record_goes_through_every_step_and_the_original_is_untouched(self):
        original = copy.deepcopy(self.data["HCR-00002-001.yaml"])
        upgraded = record_migrations.upgrade(self.data["HCR-00002-001.yaml"])
        self.assertEqual((upgraded["format"], upgraded["checked"]), (3, True))
        self.assertIn("kept by every Litterbox", upgraded["notes"])
        self.assertNotIn("custom_note", upgraded)
        self.assertEqual(self.data["HCR-00002-001.yaml"], original)

    def test_a_record_without_a_format_is_format_1(self):
        self.assertEqual(record_migrations.steps_for(self.data["HCR-00001-001.yaml"]),
                         [record_fixtures.STEP_1, record_fixtures.STEP_2])
        self.assertEqual(record_migrations.upgrade(self.data["HCR-00001-001.yaml"])["format"], 3)

    def test_a_record_halfway_only_takes_the_steps_it_still_needs(self):
        data = dict(self.data["HCR-00003-500.yaml"], format=2, notes="already renamed")
        self.assertEqual(record_migrations.steps_for(data), [record_fixtures.STEP_2])
        self.assertEqual(record_migrations.upgrade(data)["notes"], "already renamed")

    def test_upgrading_twice_is_upgrading_once(self):
        for name, data in self.data.items():
            with self.subTest(record=name):
                once = record_migrations.upgrade(data)
                self.assertEqual(record_migrations.upgrade(once), once)

    def test_reading_upgrades_and_writing_writes_the_current_format(self):
        record = load(self.data["HCR-00002-001.yaml"])
        self.assertEqual(record.extra["checked"], True)
        written = record.to_dict()
        self.assertEqual((written["format"], written["checked"]), (3, True))
        self.assertNotIn("custom_note", written)

    def test_a_record_from_a_newer_litterbox_is_still_refused(self):
        with self.assertRaisesRegex(RegistryError, "newer Litterbox"):
            load(dict(self.data["HCR-00002-001.yaml"], format=4))

    def test_writing_needs_the_vault_to_require_the_version_of_the_last_step(self):
        self.assertEqual(record_migrations.writes_need(), "0.5.0")
        for minimum, allowed in (("", False), (None, False), ("0.4.0", False), ("0.5.0", True), ("v0.5.1", True),
                                 ("nonsense", False)):
            with self.subTest(minimum=minimum):
                record_fixtures.vault_requires(minimum)
                self.assertEqual(record_migrations.may_write(), allowed)


class AskingTheServer(unittest.TestCase):
    def setUp(self):
        record_fixtures.pretend_steps(self)
        self.asked = []

    def server_says(self, minimum):
        record_migrations.configure(lambda: "", lambda: self.asked.append(1) or minimum)

    def test_an_upgrade_on_the_server_not_yet_fetched_allows_writing(self):
        self.server_says("0.5.0")
        self.assertTrue(record_migrations.may_write())
        self.assertFalse(record_migrations.may_write(ask_server=False))       # the window's check after a refresh

    def test_the_server_is_only_asked_when_the_copy_on_disk_refuses(self):
        record_migrations.configure(lambda: "0.5.0", lambda: self.asked.append(1) or "")
        self.assertTrue(record_migrations.may_write())
        self.assertEqual(self.asked, [])
        self.server_says("")
        self.assertFalse(record_migrations.may_write())
        self.assertEqual(self.asked, [1])


class RecordStoreWritesOnlyWhenAllowed(RegistryTestCase):
    def setUp(self):
        super().setUp()
        record_fixtures.use_five_digits(self)

    def test_creating_and_saving_are_refused_until_the_vault_requires_the_new_format(self):
        record = self.make(42)
        record_fixtures.pretend_steps(self)
        with self.assertRaisesRegex(RegistryError, "Upgrade records"):
            self.make(43)
        with self.assertRaisesRegex(RegistryError, "Upgrade records"):
            record_store.save(self.repo, record)
        self.assertEqual(record_store.load(self.repo, PN("HCR", 42, 1)).to_dict()["format"], 3)  # read: fine
        record_fixtures.vault_requires("0.5.0")
        record_store.save(self.repo, record)
        self.assertTrue(record_store.record_path(self.repo, PN("HCR", 42, 1)).read_text(encoding="utf-8")
                        .startswith("format: 3\n"))
        self.make(43)


if __name__ == "__main__":
    unittest.main()
