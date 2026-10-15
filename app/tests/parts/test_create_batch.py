"""Tests for creating many parts at once (parts/create_batch.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from pathlib import Path
from unittest import mock
from tests.support.vault_fixture import PART, PRT, SKIP_ON_WINDOWS, is_writable
from litterbox.records import record_store
from litterbox.parts import create_batch
from litterbox.parts import create
from litterbox.parts import number_suggestions
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.git import runner
from tests.support.create_fixture import CreateFixture


@SKIP_ON_WINDOWS
class CreateBatch(CreateFixture, unittest.TestCase):
    def test_create_many_makes_every_record_with_one_commit_and_one_push(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            specs = [create_batch.PartSpec("Valve body", "valve_body.SLDPRT", imported=True, import_path="D:/Old/valve_body.SLDPRT"),
                     create_batch.PartSpec("Bolt", "91251A540.SLDPRT", cots=True, imported=True, import_path="D:/Old/bolt.SLDPRT"),
                     create_batch.PartSpec("Hand made")]
            pns = create_batch.create_many(self.a, specs)
            self.assertEqual(pns, [PN("HCR", 2, 1), PN("HCR", 3, 1), PN("HCR", 4, 1)])
            valve, bolt, hand = (record_store.load(self.a, pn) for pn in pns)
            self.assertEqual((valve.name, valve.description, valve.imported, valve.import_path, valve.cots),
                             ("Valve body", "valve_body.SLDPRT", True, "D:/Old/valve_body.SLDPRT", False))
            self.assertEqual((bolt.cots, bolt.imported), (True, True))
            self.assertEqual((hand.imported, hand.import_path, hand.cots), (False, "", False))
            for record in (valve, bolt, hand):
                self.assertEqual(record.history[0]["event"], "created")
                self.assertFalse(is_writable(self.a / "PN-logs" / f"{record.pn}.yaml"))
            self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits + 1)
        self.assertIn("Created 3 parts: HCR-00002-001 to HCR-00004-001", self.remote_log()[0])
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(len(record_store.list_pns(self.b)), 4)

    def test_create_many_numbers_from_the_start_number_and_respects_requested_numbers(self):
        from litterbox.vault import config_write
        with self.user("Alex"):
            config_write.save(self.a, start_number=10001)
            specs = [create_batch.PartSpec("A"), create_batch.PartSpec("Wants 10002", base=10002),
                     create_batch.PartSpec("B"), create_batch.PartSpec("Wants a variant", base=10002),
                     create_batch.PartSpec("Exact", base=7, variant=5), create_batch.PartSpec("C")]
            pns = create_batch.create_many(self.a, specs)
            self.assertEqual([str(pn) for pn in pns], [
                "HCR-10001-001", "HCR-10002-001", "HCR-10003-001", "HCR-10002-002", "HCR-00007-005", "HCR-10004-001"])
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10005)

    def test_create_many_with_nothing_to_do(self):
        with self.user("Alex"):
            self.assertEqual(create_batch.create_many(self.a, []), [])
        self.assertEqual(len(self.remote_log()), 1)

    def test_one_bad_entry_stops_the_whole_batch_with_nothing_changed(self):
        commits = len(self.remote_log())
        bad_batches = [
            ("Item 3", self.specs(2) + [create_batch.PartSpec("  ")] + self.specs(2)),
            ("Item 2", [create_batch.PartSpec("Fine"), create_batch.PartSpec("x" * 101)]),
            ("Item 2", [create_batch.PartSpec("Fine"), create_batch.PartSpec("Taken", base=1, variant=1)]),
            ("Item 2", [create_batch.PartSpec("Fine", base=9, variant=1), create_batch.PartSpec("Same again", base=9, variant=1)]),
            ("Item 1", [create_batch.PartSpec("Too big", base=100000)]),
        ]
        with self.user("Alex"):
            for expected, specs in bad_batches:
                with self.subTest(expected=expected, first=specs[0].name):
                    with self.assertRaises(create.CreateError) as ctx:
                        create_batch.create_many(self.a, specs)
                    self.assertIn(expected, str(ctx.exception))
                    self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
                    self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits)

    def test_a_batch_beaten_to_the_numbers_is_renumbered_not_lost(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's part"), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                pns = create_batch.create_many(self.a, self.specs(3))
            self.assertEqual(results["bea"], PN("HCR", 2, 1))
            self.assertEqual(pns, [PN("HCR", 3, 1), PN("HCR", 4, 1), PN("HCR", 5, 1)])
            self.assertEqual(record_store.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")
            self.assert_clean(self.a)
        self.assertEqual(sum(1 for line in self.remote_log() if "Created" in line), 2)

    def test_a_requested_number_taken_in_the_race_is_reported_and_nothing_is_kept(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's seven", base=7, variant=1), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                with self.assertRaises(create.CreateError) as ctx:
                    create_batch.create_many(self.a, [create_batch.PartSpec("Fine"), create_batch.PartSpec("Alex's seven", base=7, variant=1)])
            self.assertIn("Item 2", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml", "HCR-00007-001.yaml"])
            self.assert_clean(self.a)

    def test_a_batch_whose_push_always_fails_leaves_nothing_behind(self):
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        commits = len(self.remote_log())
        with self.user("Alex"):
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(create.CreateError) as ctx:
                    create_batch.create_many(self.a, self.specs(4))
            self.assertIn("simulated network failure", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
            self.assertEqual(len(create_batch.create_many(self.a, self.specs(2))), 2)       # the numbers are still free
        self.assertEqual(len(self.remote_log()), commits + 1)

    def test_a_batch_does_not_disturb_a_checked_out_part(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            create_batch.create_many(self.a, self.specs(3))
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")
            self.assertEqual(len(self.locks(self.a)), 3)

    def test_a_big_batch_is_still_one_commit(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            pns = create_batch.create_many(self.a, self.specs(400))
            self.assertEqual(len(set(pns)), 400)
            self.assertEqual(len(record_store.list_pns(self.a)), 401)
            self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits + 1)

    def test_scan_then_manifest_then_create_many_end_to_end(self):
        import tempfile
        from litterbox.importing import manifest
        from litterbox.importing import scan
        with tempfile.TemporaryDirectory() as tmp, self.user("Alex"):
            source = Path(tmp) / "old cad"
            (source / "valves").mkdir(parents=True)
            (source / "McMaster").mkdir()
            (source / "valves" / "valve_body.SLDPRT").write_bytes(b"body")
            (source / "valves" / "valve_body.SLDDRW").write_bytes(b"drawing")
            (source / "McMaster" / "91251A540_bolt.SLDPRT").write_bytes(b"bolt")
            (source / "valves" / "valve_copy.SLDPRT").write_bytes(b"body")
            path = Path(tmp) / "manifest.yaml"
            manifest.save(scan.scan([source], repo=self.a), path)

            reviewed = manifest.load(path)
            self.assertEqual(manifest.problems(reviewed), [])
            reviewed.items[-1].include = False                       # the user leaves one out
            self.assertFalse(any(i.cots for i in reviewed.items))   # the scan never guesses
            for i in reviewed.items:
                if i.name == "91251A540 bolt":
                    i.cots = True                                   # the user marks it by hand
            items, specs = manifest.specs(reviewed)
            self.assertEqual(len(specs), 2)
            pns = create_batch.create_many(self.a, specs, message="Imported 2 parts")
            manifest.record_assignments(reviewed, items, pns)
            manifest.save(reviewed, path)

            by_name = {record_store.load(self.a, pn).name: record_store.load(self.a, pn) for pn in pns}
            bolt = by_name["91251A540 bolt"]
            self.assertEqual((bolt.cots, bolt.imported, bolt.description), (True, True, "91251A540_bolt.SLDPRT"))
            self.assertEqual(bolt.import_path, str(source / "McMaster" / "91251A540_bolt.SLDPRT"))
            valve = by_name["valve body"]
            self.assertEqual(valve.description, "valve_body.SLDPRT, valve_body.SLDDRW")
            self.assertFalse(valve.cots)
            self.assertIn("Imported 2 parts", self.remote_log()[0])

            # Running it again does nothing more: the numbers are in the manifest, and the vault remembers the paths.
            again = manifest.load(path)
            self.assertEqual(manifest.specs(again)[1], [])
            rescan = scan.scan([source], repo=self.a)
            self.assertEqual(sorted(i.include for i in rescan.items), [False, False, True])
            self.assertEqual(rescan.stats["already_imported"], 2)


if __name__ == "__main__":
    unittest.main()
