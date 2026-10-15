"""Tests for the part numbers an import proposes, numbers typed in, and numbers taken meanwhile. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import random
import unittest
from pathlib import Path
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS
from litterbox.vault import config_write
from litterbox.parts import create
from litterbox.cad.solidworks import sw_backend
from litterbox.cli import import_files as cli_import
from litterbox.importing import import_errors
from litterbox.importing import import_finish
from litterbox.importing import import_numbering
from litterbox.importing import manifest
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.git import runner
from tests.support.import_flow_fixture import ImportFlowFixture


@SKIP_ON_WINDOWS
class ImportNumbers(ImportFlowFixture, unittest.TestCase):
    def test_proposed_numbers_are_the_lowest_free_ones(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            self.assertEqual(prepared.proposal.pns(), [PN("HCR", n, 1) for n in range(2, 6)])    # 1 is in use
            self.assert_nothing_left()                            # proposing writes nothing

    def test_proposed_numbers_fill_gaps_below_the_highest(self):
        self.make_manifest()
        with self.user("Alex"):
            create.new_part(self.a, "Two")
            create.new_part(self.a, "Three")
            create.new_part(self.a, "Six", base=6)
            prepared = self.prepare()
            self.assertEqual([p.base for p in prepared.proposal.pns()], [4, 5, 7, 8])      # the gap at 4 and 5 is filled

    def test_a_gap_is_counted_from_the_lowest_free_number_not_the_highest_in_use(self):
        self.make_manifest()
        with self.user("Alex"):
            create.new_part(self.a, "Typed high", base=5000)      # the highest in use is far away; the lowest free is 2
            prepared = self.prepare(gap=100, jitter=0)
            self.assertEqual([p.base for p in prepared.proposal.pns()], [102, 103, 104, 105])
            prepared = self.prepare(gap=100, jitter=50, rng=random.Random(3))
            first = prepared.proposal.entries[0].pn.base
            self.assertTrue(102 <= first < 152)
            self.assertEqual([e.pn.base for e in prepared.proposal.entries], list(range(first, first + 4)))

    def test_the_gap_skips_numbers_already_in_use_and_loops_round(self):
        config_write.save(self.a, org="HCR", start_number=99950)        # 5 digits: the highest is 99999
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare(gap=100, jitter=0)            # 99950 + 100 is past the top, so round to 1 and on
            self.assertEqual([p.base for p in prepared.proposal.pns()], [51, 52, 53, 54])

    def test_starting_an_import_gets_the_newest_numbers_first(self):
        self.make_manifest()
        with self.user("Bea"):
            create.new_part(self.b, "Bea's new part")             # HCR-00002-001, pushed
        with self.user("Alex"):
            prepared = self.prepare()
            self.assertEqual(prepared.proposal.entries[0].pn, PN("HCR", 3, 1))
            self.assertTrue((self.a / "PN-logs" / "HCR-00002-001.yaml").exists())

    def test_the_import_and_normal_new_parts_use_the_next_free_numbers_in_turn(self):
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import()
            self.assertEqual(sorted(p.base for p in result.pns), [2, 3, 4, 5])
            self.assertEqual(create.new_part(self.a, "Ordinary part"), PN("HCR", 6, 1))

    def test_import_numbers_loop_round_after_the_highest(self):
        config_write.save(self.a, org="HCR", start_number=99998)       # 5 digits: the highest is 99999
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            self.assertEqual([p.base for p in prepared.proposal.pns()], [99998, 99999, 2, 3])

    def test_import_with_too_few_numbers_left_is_refused(self):
        self.make_manifest()
        with self.user("Alex"):
            with mock.patch.object(import_numbering, "used_numbers", return_value=(set(), set(range(1, 99999)))):
                with self.assertRaises(import_errors.ImportFailed) as caught:
                    self.prepare()
            self.assertIn("free part numbers left", str(caught.exception))

    def test_names_descriptions_and_numbers_can_be_edited_before_finishing(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            table = prepared.proposal
            table.entries[0].name = "Renamed by hand"
            table.entries[0].description = "my notes"
            table.set_pn(1, "HCR-00500-002")
            result = import_finish.finish(self.a, prepared, log=lambda *_: None)
            prepared.close()
            self.assertEqual(result.pns[1], PN("HCR", 500, 2))
            self.assertTrue((self.a / "cad" / f"HCR-00500-002{Path(result.plan.order[0]).suffix}").exists()
                            or any(n.startswith("HCR-00500-002") for n in self.cad_names()))
            record = record_store.load(self.a, result.pns[0])
            self.assertEqual((record.name, record.description), ("Renamed by hand", "my notes"))
            saved = manifest.load(self.manifest_path)
            self.assertIn("Renamed by hand", [i.name for i in saved.items])
            self.assert_clean(self.a)

    def test_a_typed_number_that_is_taken_stops_the_import_but_keeps_the_table(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(2, "HCR-00001-001")          # exists already
            before = [e.pn for e in prepared.proposal.entries]
            with self.assertRaises(import_errors.PNConflict) as ctx:
                import_finish.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([(c.index, c.manual) for c in ctx.exception.conflicts], [(2, True)])
            self.assertIn("Front upright", str(ctx.exception))
            self.assertEqual(self.fake.copied, [])                # refused before copying anything
            self.assert_nothing_left()
            self.assertEqual(prepared.proposal.entries[2].pn, PN("HCR", 1, 1))        # the typed number is untouched
            self.assertEqual([e.pn for e in prepared.proposal.entries if not e.manual],
                             [b for i, b in enumerate(before) if i != 2])
            prepared.proposal.set_pn(2, "HCR-00700-001")           # the user fixes the red row...
            result = import_finish.finish(self.a, prepared, log=lambda *_: None)    # ...and finishes again
            prepared.close()
            self.assertIn(PN("HCR", 700, 1), result.pns)
            self.assert_clean(self.a)

    def test_automatic_numbers_taken_meanwhile_are_replaced_without_fuss(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            self.assertEqual(prepared.proposal.entries[0].pn, PN("HCR", 2, 1))
        with self.user("Bea"):
            create.new_part(self.b, "Bea one")                    # takes 2
            create.new_part(self.b, "Bea two")                    # takes 3
        with self.user("Alex"):
            prepared.proposal.set_pn(3, "HCR-00900-001")           # a typed one is fine and stays
            result = import_finish.finish(self.a, prepared, log=lambda *_: None)
            prepared.close()
            self.assertEqual(sorted(p.base for p in result.pns), [4, 5, 6, 900])
            self.assertEqual(sorted(r[0] for r in result.renumbered), [0, 1])
            self.assert_clean(self.a)

    def test_typed_and_automatic_conflicts_together(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(0, "HCR-00003-001")           # typed, and about to be taken
        with self.user("Bea"):
            create.new_part(self.b, "Bea one")                    # 2 (automatic row 0 used to be here)
            create.new_part(self.b, "Bea two")                    # 3
        with self.user("Alex"):
            with self.assertRaises(import_errors.PNConflict) as ctx:
                import_finish.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [0])
            # the automatic rows were already moved on to free numbers, ready for the next try
            self.assertTrue(all(e.pn.base >= 4 for e in prepared.proposal.entries[1:]))
            prepared.proposal.reset_pn(0)                          # hand row 0 back to Litterbox
            result = import_finish.finish(self.a, prepared, log=lambda *_: None)
            prepared.close()
            self.assertEqual(len(set(result.pns)), 4)
            self.assert_nothing_left_but_import(result)

    def test_a_typed_number_taken_at_the_last_moment_is_reported_and_cleaned_up(self):
        self.make_manifest()
        real_run = runner.run
        state = {"done": False}

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and not state["done"] and Path(repo) == self.a:
                state["done"] = True
                with self.user("Bea"):
                    create.new_part(self.b, "Bea's", base=800)
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(1, "HCR-00800-001")
            with mock.patch.object(runner, "run", run):
                with self.assertRaises(import_errors.PNConflict) as ctx:
                    import_finish.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [1])
            self.assertEqual(self.cad_names(), ["HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.SLDPRT"])
            self.assert_clean(self.a)
            prepared.proposal.set_pn(1, "HCR-00801-001")
            self.assertEqual(len(import_finish.finish(self.a, prepared, log=lambda *_: None).pns), 4)
            prepared.close()

    def test_the_same_number_twice_in_the_table_is_a_conflict(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(0, "HCR-00600-001")
            prepared.proposal.set_pn(1, "HCR-00600-001")
            with self.assertRaises(import_errors.PNConflict) as ctx:
                import_finish.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [1])
            self.assertIn("twice", str(ctx.exception))

    def test_bad_typed_numbers_are_rejected_when_typed(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            for text in ("", "banana", "HCR-00000-001", "HCR-00005-000", "HCR-5-1"):
                with self.assertRaises(import_errors.ImportFailed):
                    prepared.proposal.set_pn(0, text)
            prepared.proposal.set_pn(0, "XYZ-00600-001")           # a valid PN for another organization
            with self.assertRaises(import_errors.PNConflict) as ctx:
                import_finish.finish(self.a, prepared, log=lambda *_: None)
            self.assertIn("different organization", str(ctx.exception))

    def test_cancelling_after_a_conflict_retry_still_leaves_nothing(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(0, "HCR-00001-001")
            with self.assertRaises(import_errors.PNConflict):
                import_finish.finish(self.a, prepared, log=lambda *_: None)
            prepared.proposal.reset_pn(0)
            with self.assertRaises(import_errors.ImportCancelled):
                import_finish.finish(self.a, prepared, cancel=lambda: len(self.fake.copied) >= 2, log=lambda *_: None)
            prepared.close()
            self.assert_nothing_left()

    def test_command_line_dry_run_and_recover(self):
        self.make_manifest()
        with self.user("Alex"):
            with mock.patch.object(sw_backend, "SolidWorksBackend", lambda: self.fake):
                self.assertEqual(cli_import.main([str(self.a), str(self.manifest_path), "--dry-run"]), 0)
                self.assertEqual(cli_import.main([str(self.a), "--recover"]), 0)
                self.assertEqual(cli_import.main([str(self.a), str(self.manifest_path)]), 0)
                self.assertEqual(cli_import.main([str(self.a), str(self.manifest_path)]), 1)     # nothing left to import


if __name__ == "__main__":
    unittest.main()
