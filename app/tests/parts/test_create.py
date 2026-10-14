"""
Two-user tests for create.py (New Part / New Variant).

They run the real code against real git repos (a bare "remote" plus one clone
for each of two simulated users, Alex and Bea), with a fake git-lfs standing in
for Git LFS. They need Linux, macOS or WSL and are skipped on Windows.

Run from the app folder with:  python -m unittest discover -s tests -t . -v
"""

import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock

from tests.support.vault_fixture import PART, PRT, SKIP_ON_WINDOWS, TwoUserVault, git, is_writable

from litterbox.records import registry
from litterbox.parts import create
from litterbox.core.pn import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.git import runner


@SKIP_ON_WINDOWS
class CreateFlow(TwoUserVault, unittest.TestCase):
    # -- helpers -----------------------------------------------------------
    def assert_clean(self, repo):
        """Nothing left over: no changed or untracked files, and no commits waiting to be pushed."""
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "@{u}..HEAD"), "0")

    def record_names(self, repo):
        return sorted(p.name for p in (Path(repo) / "PN-logs").iterdir())

    # -- New Part ----------------------------------------------------------
    def test_new_part_takes_the_lowest_free_number_and_pushes_it(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "  Rear   upright\n")
            self.assertEqual(pn, PN("HCR", 2, 1))
            record = registry.load(self.a, pn)
            self.assertEqual((record.name, record.description, record.created_by, record.status),
                             ("Rear upright", "", "Alex", "in_work"))
            self.assertEqual(record.history[0]["event"], "created")
            self.assertIn("HCR-00002-001: Created - Rear upright", self.remote_log())
            self.assertFalse(is_writable(self.a / "PN-logs/HCR-00002-001.yaml"))   # read-only until checked out
            self.assertEqual(self.status_of(self.a, pn).state, "Created, no CAD files yet")
            self.assert_clean(self.a)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(registry.load(self.b, pn).created_by, "Alex")

    def test_gaps_are_filled_and_manual_numbers_are_skipped(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Typed in by hand", base=4), PN("HCR", 4, 1))
            numbers = [create.new_part(self.a, f"Part {n}").base for n in range(3)]
            self.assertEqual(numbers, [2, 3, 5])

    def test_numbers_loop_round_to_the_bottom_after_the_highest(self):
        from litterbox.vault import config
        config.save(self.a, org="HCR", start_number=99998)       # 5 digits: the highest is 99999
        with self.user("Alex"):
            numbers = [create.new_part(self.a, f"Part {n}").base for n in range(4)]
            self.assertEqual(numbers, [99998, 99999, 2, 3])      # 1 is already in use; zero is never used
            self.assertEqual(create.suggest_part_number(self.a), 4)

    def test_a_vault_with_no_numbers_left_says_so_plainly(self):
        with self.user("Alex"):
            with mock.patch.object(registry, "used_bases", return_value=set(range(1, 100000))):
                with self.assertRaises(create.CreateError) as caught:
                    create.new_part(self.a, "One too many")
                self.assertIn("no part numbers left", str(caught.exception))
                with self.assertRaises(create.CreateError):
                    create.suggest_part_number(self.a)
            self.assertEqual(sorted(p.name for p in (self.a / "PN-logs").iterdir()), ["HCR-00001-001.yaml"])

    def test_part_number_in_use_gets_its_lowest_free_variant(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Right hand", base=1), PN("HCR", 1, 2))
            self.assertEqual(create.new_part(self.a, "Left hand", base=1), PN("HCR", 1, 3))
            self.assertEqual(create.new_part(self.a, "Typed variant", base=1, variant=9), PN("HCR", 1, 9))
            self.assertEqual(create.new_part(self.a, "Fresh base", base=300), PN("HCR", 300, 1))
            self.assert_clean(self.a)

    def test_variant_alone_goes_on_the_next_free_part_number(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Spare", variant=501), PN("HCR", 2, 501))
            self.assertEqual(create.new_part(self.a, "Next", variant=501), PN("HCR", 3, 501))
            self.assertEqual(create.new_part(self.a, "Plain"), PN("HCR", 4, 1))

    def test_suggested_numbers_for_the_empty_boxes(self):
        with self.user("Alex"):
            self.assertEqual(create.suggest_numbers(self.a), (2, 1))
            self.assertEqual(create.suggest_numbers(self.a, 1), (1, 2))        # in use: lowest free variant
            self.assertEqual(create.suggest_numbers(self.a, 77), (77, 1))      # unused: 001
            create.new_part(self.a, "Right hand", base=1)
            self.assertEqual(create.suggest_numbers(self.a, 1), (1, 3))
            from litterbox.vault import config
            config.save(self.a, start_number=10001)
            self.assertEqual(create.suggest_numbers(self.a), (10001, 1))
            with self.assertRaises(create.CreateError):
                create.suggest_numbers(self.a, 0)

    def test_check_numbers_says_what_would_be_created_and_whether_it_is_free(self):
        with self.user("Alex"):
            check = create.check_numbers(self.a)
            self.assertEqual((check.pn, check.taken), (PN("HCR", 2, 1), False))
            check = create.check_numbers(self.a, 1, 1)
            self.assertEqual((check.pn, check.taken, check.name, check.status),
                             (PN("HCR", 1, 1), True, "Front upright", "in_work"))
            check = create.check_numbers(self.a, 1)                       # variant left empty
            self.assertEqual((check.pn, check.taken), (PN("HCR", 1, 2), False))
            check = create.check_numbers(self.a, None, 501)               # base left empty
            self.assertEqual((check.pn, check.taken), (PN("HCR", 2, 501), False))
            self.assertFalse(create.check_numbers(self.a, 1, 2).taken)
            for bad in ((0, None), (None, 0), (None, 1000), (100000, None)):
                with self.subTest(bad=bad), self.assertRaises(create.CreateError):
                    create.check_numbers(self.a, *bad)

    def test_void_parts_still_count_as_in_use(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Scrapped idea", base=50, variant=1)
            lifecycle.void(self.a, pn, "Not needed")
            check = create.check_numbers(self.a, 50, 1)
            self.assertEqual((check.taken, check.name, check.status), (True, "Scrapped idea", "void"))
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "Reuse attempt", base=50, variant=1)

    def test_automatic_numbers_start_at_start_number_whatever_exists_below_it(self):
        from litterbox.vault import config
        with self.user("Alex"):
            config.save(self.a, start_number=10001)             # HCR-00001-001 already exists
            self.assertEqual(create.suggest_part_number(self.a), 10001)
            self.assertEqual(create.new_part(self.a, "First of the range"), PN("HCR", 10001, 1))
            self.assertEqual(create.suggest_part_number(self.a), 10002)
            self.assertEqual(create.new_part(self.a, "Typed higher", base=10004, variant=1), PN("HCR", 10004, 1))
            self.assertEqual(create.new_part(self.a, "Second"), PN("HCR", 10002, 1))
            self.assertEqual(create.new_part(self.a, "Third"), PN("HCR", 10003, 1))
            self.assertEqual(create.new_part(self.a, "Fifth"), PN("HCR", 10005, 1))
            self.assertEqual(create.new_part(self.a, "Typed below", base=2, variant=1), PN("HCR", 2, 1))
            self.assertEqual(create.suggest_part_number(self.a), 10006)       # a part at 00002 changes nothing

    def test_explicit_part_number_and_variant_that_are_taken_are_refused(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            with self.assertRaises(create.CreateError) as ctx:
                create.new_part(self.a, "Duplicate", base=1, variant=1)
            message = str(ctx.exception)
            self.assertIn("HCR-00001-001", message)
            self.assertIn("Front upright", message)          # says who has it
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits)

    def test_org_can_be_given_or_set_in_the_vault(self):
        with self.user("Alex"):
            self.assertEqual(create.new_part(self.a, "Other org", org="fsae"), PN("FSAE", 1, 1))
            config_file = self.a / ".litterbox" / "config.yaml"
            config_file.parent.mkdir()
            config_file.write_text("org: FSAE\n", encoding="utf-8")
            self.assertEqual(create.new_part(self.a, "From config"), PN("FSAE", 2, 1))

    def test_description_is_checked_before_any_git_work(self):
        with self.user("Alex"):
            with mock.patch.object(runner, "run", side_effect=AssertionError("git should not run")):
                for bad in ("", "   \n ", "x" * 201):
                    with self.subTest(bad=bad[:10]):
                        with self.assertRaises(create.CreateError):
                            create.new_part(self.a, bad)
            self.assert_clean(self.a)

    def test_void_numbers_are_never_reused(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Never built")
            lifecycle.void(self.a, pn, "Not needed")
            self.assertEqual(create.new_part(self.a, "Next one"), PN("HCR", 3, 1))

    # -- New Variant -------------------------------------------------------
    def test_new_variant_numbers(self):
        with self.user("Alex"):
            self.assertEqual(create.new_variant(self.a, 1, "Right hand"), PN("HCR", 1, 2))
            self.assertEqual(create.new_variant(self.a, 1, "Long", variant=5), PN("HCR", 1, 5))
            self.assertEqual(create.new_variant(self.a, 1, "Short"), PN("HCR", 1, 3))      # fills the gap
            self.assertIn("HCR-00001-005: Created - Long", self.remote_log())

    def test_name_is_required_and_description_is_optional(self):
        with self.user("Alex"):
            for bad in ("", "   "):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, bad)
                self.assertIn("name is required", str(ctx.exception))
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "x" * 101)
            with self.assertRaises(create.CreateError):
                create.new_part(self.a, "Fine", description="x" * 501)
            pn = create.new_part(self.a, "Gusset", description="  for the  rear\nframe ")
            self.assertEqual((registry.load(self.a, pn).name, registry.load(self.a, pn).description),
                             ("Gusset", "for the rear frame"))
            pn = create.new_variant(self.a, 1, "Gusset, mirrored")
            self.assertEqual(registry.load(self.a, pn).description, "")
            self.assert_clean(self.a)

    def test_new_variant_needs_no_existing_base(self):
        with self.user("Alex"):
            self.assertEqual(create.new_variant(self.a, 12345, "Spare bracket", variant=501),
                             PN("HCR", 12345, 501))
            self.assertEqual(create.new_variant(self.a, 777, "Another"), PN("HCR", 777, 1))
            self.assertIn("HCR-12345-501: Created - Spare bracket", self.remote_log())
            self.assert_clean(self.a)

    def test_start_number_from_vault_config(self):
        from litterbox.vault import config
        with self.user("Alex"):
            config.save(self.a, start_number=10001)
            self.assertEqual(create.suggest_part_number(self.a), 10001)
            self.assertEqual(create.new_part(self.a, "First of the range"), PN("HCR", 10001, 1))
            self.assertEqual(create.new_part(self.a, "Second"), PN("HCR", 10002, 1))
            self.assertEqual(create.suggest_part_number(self.a), 10003)

    def test_new_variant_refuses_taken_numbers(self):
        with self.user("Alex"):
            with self.assertRaises(create.CreateError) as ctx:
                create.new_variant(self.a, 1, "Again", variant=1)
            self.assertIn("already in use", str(ctx.exception))
            self.assertIn("Front upright", str(ctx.exception))
            for bad in (0, 1000):
                with self.assertRaises(create.CreateError):
                    create.new_variant(self.a, 1, "Out of range", variant=bad)
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_suggestions_and_listing(self):
        with self.user("Alex"):
            create.new_variant(self.a, 1, "Right hand")
            self.assertEqual(create.suggest_part_number(self.a), 2)
            self.assertEqual(create.suggest_variant_number(self.a, 1), 3)
            self.assertEqual(create.suggest_variant_number(self.a, 50), 1)
            rows = create.list_variants(self.a, 1)
            self.assertEqual([(str(r.pn), r.name) for r in rows],
                             [("HCR-00001-001", "Front upright"), ("HCR-00001-002", "Right hand")])
            self.assertEqual(create.list_variants(self.a, 50), [])

    # -- Two people at the same moment --------------------------------------
    def rival_pushes_first(self, rival_call, results):
        """A replacement for runner.run that lets Bea's creation land just before Alex's push."""
        real_run = runner.run
        state = {"done": False}

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and not state["done"] and Path(repo) == self.a:
                state["done"] = True
                with self.user("Bea"):
                    results["bea"] = rival_call()
            return real_run(command, repo, quiet)

        return run

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
            self.assertEqual(registry.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")
            self.assertEqual(registry.load(self.a, pn).created_by, "Alex")
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
            self.assertEqual(registry.load(self.a, PN("HCR", 7, 1)).created_by, "Bea")
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

    # -- Many at once ------------------------------------------------------
    def specs(self, count, **fields):
        return [create.PartSpec(name=f"Part {n}", **fields) for n in range(1, count + 1)]

    def test_create_many_makes_every_record_with_one_commit_and_one_push(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            specs = [create.PartSpec("Valve body", "valve_body.SLDPRT", imported=True, import_path="D:/Old/valve_body.SLDPRT"),
                     create.PartSpec("Bolt", "91251A540.SLDPRT", cots=True, imported=True, import_path="D:/Old/bolt.SLDPRT"),
                     create.PartSpec("Hand made")]
            pns = create.create_many(self.a, specs)
            self.assertEqual(pns, [PN("HCR", 2, 1), PN("HCR", 3, 1), PN("HCR", 4, 1)])
            valve, bolt, hand = (registry.load(self.a, pn) for pn in pns)
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
            self.assertEqual(len(registry.list_pns(self.b)), 4)

    def test_create_many_numbers_from_the_start_number_and_respects_requested_numbers(self):
        from litterbox.vault import config
        with self.user("Alex"):
            config.save(self.a, start_number=10001)
            specs = [create.PartSpec("A"), create.PartSpec("Wants 10002", base=10002),
                     create.PartSpec("B"), create.PartSpec("Wants a variant", base=10002),
                     create.PartSpec("Exact", base=7, variant=5), create.PartSpec("C")]
            pns = create.create_many(self.a, specs)
            self.assertEqual([str(pn) for pn in pns], [
                "HCR-10001-001", "HCR-10002-001", "HCR-10003-001", "HCR-10002-002", "HCR-00007-005", "HCR-10004-001"])
            self.assertEqual(create.suggest_part_number(self.a), 10005)

    def test_create_many_with_nothing_to_do(self):
        with self.user("Alex"):
            self.assertEqual(create.create_many(self.a, []), [])
        self.assertEqual(len(self.remote_log()), 1)

    def test_one_bad_entry_stops_the_whole_batch_with_nothing_changed(self):
        commits = len(self.remote_log())
        bad_batches = [
            ("Item 3", self.specs(2) + [create.PartSpec("  ")] + self.specs(2)),
            ("Item 2", [create.PartSpec("Fine"), create.PartSpec("x" * 101)]),
            ("Item 2", [create.PartSpec("Fine"), create.PartSpec("Taken", base=1, variant=1)]),
            ("Item 2", [create.PartSpec("Fine", base=9, variant=1), create.PartSpec("Same again", base=9, variant=1)]),
            ("Item 1", [create.PartSpec("Too big", base=100000)]),
        ]
        with self.user("Alex"):
            for expected, specs in bad_batches:
                with self.subTest(expected=expected, first=specs[0].name):
                    with self.assertRaises(create.CreateError) as ctx:
                        create.create_many(self.a, specs)
                    self.assertIn(expected, str(ctx.exception))
                    self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
                    self.assert_clean(self.a)
        self.assertEqual(len(self.remote_log()), commits)

    def test_a_batch_beaten_to_the_numbers_is_renumbered_not_lost(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's part"), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                pns = create.create_many(self.a, self.specs(3))
            self.assertEqual(results["bea"], PN("HCR", 2, 1))
            self.assertEqual(pns, [PN("HCR", 3, 1), PN("HCR", 4, 1), PN("HCR", 5, 1)])
            self.assertEqual(registry.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")
            self.assert_clean(self.a)
        self.assertEqual(sum(1 for line in self.remote_log() if "Created" in line), 2)

    def test_a_requested_number_taken_in_the_race_is_reported_and_nothing_is_kept(self):
        results = {}
        rival = self.rival_pushes_first(lambda: create.new_part(self.b, "Bea's seven", base=7, variant=1), results)
        with self.user("Alex"):
            with mock.patch.object(runner, "run", rival):
                with self.assertRaises(create.CreateError) as ctx:
                    create.create_many(self.a, [create.PartSpec("Fine"), create.PartSpec("Alex's seven", base=7, variant=1)])
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
                    create.create_many(self.a, self.specs(4))
            self.assertIn("simulated network failure", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
            self.assertEqual(len(create.create_many(self.a, self.specs(2))), 2)       # the numbers are still free
        self.assertEqual(len(self.remote_log()), commits + 1)

    def test_a_batch_does_not_disturb_a_checked_out_part(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            create.create_many(self.a, self.specs(3))
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")
            self.assertEqual(len(self.locks(self.a)), 3)

    def test_a_big_batch_is_still_one_commit(self):
        commits = len(self.remote_log())
        with self.user("Alex"):
            pns = create.create_many(self.a, self.specs(400))
            self.assertEqual(len(set(pns)), 400)
            self.assertEqual(len(registry.list_pns(self.a)), 401)
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
            pns = create.create_many(self.a, specs, message="Imported 2 parts")
            manifest.record_assignments(reviewed, items, pns)
            manifest.save(reviewed, path)

            by_name = {registry.load(self.a, pn).name: registry.load(self.a, pn) for pn in pns}
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

    # -- When things go wrong ----------------------------------------------
    def test_a_push_that_always_fails_leaves_nothing_behind(self):
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        commits = len(self.remote_log())
        with self.user("Alex"):
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "Doomed")
            self.assertIn(f"{create.ATTEMPTS} tries", str(ctx.exception))
            self.assertIn("simulated network failure", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)
            self.assertEqual(create.new_part(self.a, "Works now"), PN("HCR", 2, 1))   # the number is still free
        self.assertEqual(len(self.remote_log()), commits + 1)

    def test_offline_at_the_start_changes_nothing(self):
        real_run = runner.run

        def offline(command, repo, quiet=False):
            if command[:2] == ["git", "pull"]:
                raise LitterboxError("simulated: could not resolve host")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", offline):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "No network")
            self.assertIn("online", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_connection_lost_after_a_failed_push_changes_nothing(self):
        real_run = runner.run
        pulls = {"count": 0}

        def flaky(command, repo, quiet=False):
            if command[:2] == ["git", "pull"]:
                pulls["count"] += 1
                if pulls["count"] > 1:                      # the first pull works, then the network drops
                    raise LitterboxError("simulated: could not resolve host")
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated: connection reset")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", flaky):
                with self.assertRaises(create.CreateError) as ctx:
                    create.new_part(self.a, "Lost connection")
            self.assertIn("can't be reached", str(ctx.exception))
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assert_clean(self.a)

    def test_a_checked_out_part_is_not_disturbed_by_a_creation(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            pn = create.new_part(self.a, "Another part")
            self.assertEqual(pn, PN("HCR", 2, 1))
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")      # edit still there
            self.assertEqual(len(self.locks(self.a)), 3)                              # still checked out
            self.assertTrue(is_writable(self.a / PRT))
            self.assertEqual(git(self.remote, "show", f"main:{PRT}"), "version 1")     # edit was not uploaded
            self.assertEqual(sum(1 for line in self.remote_log() if "Created" in line), 1)
            self.assertTrue(checkin.checkin(self.a, PART, "Finished my edit").uploaded)   # and it can still be checked in

    def test_a_failed_push_does_not_disturb_a_checked_out_part_either(self):
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"half-finished edit")
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(create.CreateError):
                    create.new_part(self.a, "Doomed")
            self.assertEqual((self.a / PRT).read_bytes(), b"half-finished edit")
            self.assertEqual(len(self.locks(self.a)), 3)
            self.assertEqual(self.record_names(self.a), ["HCR-00001-001.yaml"])
            self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    # -- Using a created number afterwards -----------------------------------
    def test_a_created_part_can_be_checked_out_and_given_files(self):
        with self.user("Alex"):
            pn = create.new_part(self.a, "Rear upright")
            self.assertEqual(checkout.checkout(self.a, pn).files, [])
            prt = "cad/HCR-00002-001_A.SLDPRT"
            (self.a / prt).write_bytes(b"brand new part")
            self.assertEqual(checkin.checkin(self.a, pn, "First version").files, [prt])
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(self.status_of(self.a, pn).state, "Available")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual((self.b / prt).read_bytes(), b"brand new part")

    # -- Command line --------------------------------------------------------
    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = create.main([str(self.a), *args])
        return code, out.getvalue()

    def test_command_line(self):
        with self.user("Alex"):
            code, out = self.run_cli("part", "From the command line")
            self.assertEqual(code, 0)
            self.assertIn("Created HCR-00002-001", out)
            code, out = self.run_cli("variant", "1", "Right hand", "--variant", "4")
            self.assertEqual(code, 0)
            self.assertIn("Created HCR-00001-004", out)
            code, out = self.run_cli("variants", "1")
            self.assertIn("HCR-00001-004", out)
            self.assertIn("Next free variant: 002", out)
            code, out = self.run_cli("next")
            self.assertIn("Next free part number: 00003", out)
            code, out = self.run_cli("part", "Duplicate", "--number", "1", "--variant", "1")
            self.assertEqual(code, 1)
            self.assertIn("ERROR", out)


if __name__ == "__main__":
    unittest.main()
