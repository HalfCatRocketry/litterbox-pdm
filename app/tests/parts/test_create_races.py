"""Tests for two people creating parts at the same time. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS
from litterbox.records import record_store
from litterbox.parts import create
from litterbox.core.part_number import PN
from litterbox.git import runner
from tests.support.create_fixture import CreateFixture


@SKIP_ON_WINDOWS
class CreateRaces(CreateFixture, unittest.TestCase):
    def test_two_people_creating_at_once_both_get_a_number(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's part"), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                pn = create.new_part(self.a, "Alex's part")
            self.assertEqual(results["bea"], PN("HCR", 2, 1))        # Bea pushed first and got 2
            self.assertEqual(pn, PN("HCR", 3, 1))                    # Alex quietly moved on to 3
            self.assertEqual(self.record_names(self.a),
                             ["HCR-00001-001.yaml", "HCR-00002-001.yaml", "HCR-00003-001.yaml"])
            self.assertEqual(record_store.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")
            self.assertEqual(record_store.load(self.a, pn).created_by, "Alex")
            self.assert_clean(self.a)
        log = self.remote_log()
        self.assertIn("HCR-00002-001: Created - Bea's part", log)
        self.assertIn("HCR-00003-001: Created - Alex's part", log)
        self.assertEqual(sum(1 for line in log if "Created" in line), 2)

    def test_manual_number_taken_in_the_race_is_reported(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's seven", base=7, variant=1), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "Alex's seven", base=7, variant=1)
            self.assertIn("00007", str(ctx.exception))
            self.assertIn("already in use", str(ctx.exception))
            self.assertIn("Bea's seven", str(ctx.exception))
            self.assertEqual(record_store.load(self.a, PN("HCR", 7, 1)).created_by, "Bea")
            self.assert_clean(self.a)
        self.assertEqual(sum(1 for line in self.remote_log() if "Created" in line), 1)

    def test_part_number_without_variant_moves_to_the_next_variant_when_beaten(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's seven", base=7), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                pn = create.new_part(self.a, "Alex's seven", base=7)
            self.assertEqual((results["bea"], pn), (PN("HCR", 7, 1), PN("HCR", 7, 2)))
            self.assert_clean(self.a)

    def test_two_people_creating_variants_at_once(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_variant(self.b, 1, "Bea's variant"), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                pn = create.new_variant(self.a, 1, "Alex's variant")
            self.assertEqual(results["bea"], PN("HCR", 1, 2))
            self.assertEqual(pn, PN("HCR", 1, 3))
            self.assert_clean(self.a)


if __name__ == "__main__":
    unittest.main()
