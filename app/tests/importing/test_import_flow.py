"""Tests for importing (prepare, finish, recover), using a pretend SolidWorks and the two-user vault. The important ones are the leaves-nothing-behind tests: cancelling, failing, losing a race for the numbers and crashing must each leave the vault and its git exactly as they were. They need Linux, macOS or WSL."""

import os
import random
import unittest
from pathlib import Path
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, git, is_writable
from litterbox.vault import config_write
from litterbox.parts import create
from litterbox.cad.solidworks import sw_backend
from litterbox.cli import import_files as cli_import
from litterbox.importing import import_errors
from litterbox.importing import import_finish
from litterbox.importing import import_journal
from litterbox.importing import import_numbering
from litterbox.importing import import_prepare
from litterbox.importing import manifest
from litterbox.records import record_store
from litterbox.core.part_number import PN
from tests.support.import_fixture import ImportFixture
from litterbox.errors import LitterboxError
from litterbox.parts import get_latest
from litterbox.git import runner


@SKIP_ON_WINDOWS
class ImportFlow(ImportFixture, unittest.TestCase):
    # -- the happy path ----------------------------------------------------
    def test_import_copies_renames_repoints_and_commits_everything_at_once(self):
        before = self.originals()
        self.make_manifest()
        commits = len(self.remote_log())
        with self.user("Alex"):
            result = self.run_import()
            self.assertEqual(len(result.pns), 4)
            self.assertEqual(self.originals(), before)                     # originals untouched
            cad = self.a / "cad"
            # the 4 items are numbered 2..5 in manifest order; the drawing shares its model's number
            names = self.cad_names()
            self.assertEqual(len([n for n in names if n.endswith(".SLDDRW")]), 2)     # the old drawing + the imported one
            by_name = {record_store.load(self.a, pn).name: pn for pn in result.pns}
            self.assertEqual(sorted(by_name), ["p1", "p3", "sub", "top"])
            top = by_name["top"]
            top_text = (cad / f"{top}_A.SLDASM").read_text()
            self.assertIn(f"ref: {cad / (str(by_name['sub']) + '_A.SLDASM')}", top_text)       # the stale folder is repointed
            self.assertIn(f"ref: {cad / (str(by_name['p1']) + '_A.SLDPRT')}", top_text)
            self.assertNotIn("old cad", top_text)
            drawing = (cad / f"{top}_A.SLDDRW").read_text()
            self.assertIn(f"ref: {cad / (str(top) + '_A.SLDASM')}", drawing)
            sub_text = (cad / f"{by_name['sub']}_A.SLDASM").read_text()
            self.assertIn(f"ref: {cad / (str(by_name['p3']) + '_A.SLDPRT')}", sub_text)
            # records
            record = record_store.load(self.a, top)
            self.assertTrue(record.imported)
            self.assertFalse(record.cots)
            self.assertEqual(record.description, "top.SLDASM, top.SLDDRW")
            self.assertEqual(record.import_path, str(self.src / "top.SLDASM"))
            # one commit, one push, nothing pending, read-only, no journal, manifest updated
            self.assertEqual(len(self.remote_log()), commits + 1)
            self.assertIn("Imported 4 parts", self.remote_log()[0])
            self.assert_clean(self.a)
            self.assertFalse(is_writable(cad / f"{top}_A.SLDASM"))
            self.assertFalse((self.a / ".git" / import_journal.JOURNAL_NAME).exists())
            self.assertEqual(sorted(i.pn for i in manifest.load(self.manifest_path).items), sorted(map(str, result.pns)))
            # the status list shows them as ordinary parts with files
            self.assertEqual(self.status_of(self.a, top).kind, "ok")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue((self.b / "cad" / f"{top}_A.SLDASM").exists())

    def test_running_it_again_has_nothing_to_do(self):
        self.make_manifest()
        with self.user("Alex"):
            self.run_import()
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("nothing left to import", str(ctx.exception))

    def test_dry_run_changes_nothing(self):
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import(dry_run=True)
            self.assertTrue(result.dry_run)
            self.assertEqual(len(result.pns), 4)
            self.assertEqual(len(result.plan.order), 5)
            self.assertEqual(self.fake.copied, [])
            self.assert_nothing_left()
            self.assertTrue(all(not i.pn for i in manifest.load(self.manifest_path).items))

    def test_children_are_copied_before_their_parents_and_drawings_last(self):
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import()
        order = [os.path.basename(p) for p in result.plan.order]
        self.assertLess(order.index("p3.SLDPRT"), order.index("sub.SLDASM"))
        self.assertLess(order.index("sub.SLDASM"), order.index("top.SLDASM"))
        self.assertEqual(order[-1], "top.SLDDRW")

    # -- cancelling and failing ---------------------------------------------
    def test_cancel_in_the_middle_removes_every_copy_and_frees_the_numbers(self):
        self.make_manifest()
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportCancelled):
                self.run_import(cancel=lambda: len(self.fake.copied) >= 3)
            self.assertEqual(len(self.fake.copied), 3)                    # it had really started
            self.assert_nothing_left()
            self.assertTrue(all(not i.pn for i in manifest.load(self.manifest_path).items))   # manifest untouched
            # a second attempt starts from scratch and gets the very same numbers
            self.fake.copied.clear()
            result = self.run_import()
            self.assertEqual(sorted(result.pns), [PN("HCR", n, 1) for n in range(2, 6)])
            self.assert_clean(self.a)

    def test_cancel_after_everything_was_copied_but_before_the_commit(self):
        self.make_manifest()
        with self.user("Alex"):
            calls = {"n": 0}

            def cancel():
                calls["n"] += 1
                return len(self.fake.copied) >= 5 and calls["n"] > 0 and self.fake.copied and \
                    os.path.exists(self.fake.copied[-1])

            with self.assertRaises(import_errors.ImportCancelled):
                self.run_import(cancel=cancel)
            self.assertEqual(len(self.fake.copied), 5)
            self.assert_nothing_left()
            self.assertEqual(self.remote_log()[0], "Start vault")

    def test_cancel_before_anything_starts(self):
        self.make_manifest()
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportCancelled):
                self.run_import(cancel=lambda: True)
            self.assertEqual(self.fake.copied, [])
            self.assert_nothing_left()

    def test_solidworks_failing_midway_leaves_nothing(self):
        self.make_manifest()
        self.fake.fail_on = "top.SLDASM"
        with self.user("Alex"):
            with self.assertRaises(RuntimeError):
                self.run_import()
            self.assertGreaterEqual(len(self.fake.copied), 1)
            self.assert_nothing_left()
            self.fake.fail_on = None
            self.assertEqual(len(self.run_import().pns), 4)

    def test_a_reference_that_cannot_be_changed_stops_the_import_cleanly(self):
        self.make_manifest()
        self.fake.refuse_repoint = True
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("would not change the reference", str(ctx.exception))
            self.assert_nothing_left()

    def test_keyboard_interrupt_also_cleans_up(self):
        self.make_manifest()
        original = self.fake.copy

        def interrupted(src, dst):
            original(src, dst)
            if len(self.fake.copied) == 2:
                raise KeyboardInterrupt()

        self.fake.copy = interrupted
        with self.user("Alex"):
            with self.assertRaises(KeyboardInterrupt):
                self.run_import()
            self.assert_nothing_left()

    def test_a_push_that_always_fails_leaves_nothing_behind(self):
        self.make_manifest()
        real_run = runner.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", broken):
                with self.assertRaises(LitterboxError):
                    self.run_import()
            self.assert_nothing_left()
            self.assertEqual(len(self.run_import().pns), 4)

    def test_offline_at_the_start_changes_nothing(self):
        self.make_manifest()
        real_run = runner.run

        def offline(command, repo, quiet=False):
            if command[:2] == ["git", "pull"]:
                raise LitterboxError("simulated: no connection")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", offline):
                with self.assertRaises(import_errors.ImportFailed):
                    self.run_import()
            self.assertEqual(self.fake.copied, [])
            self.assert_nothing_left()

    # -- someone else gets the numbers first --------------------------------
    def test_losing_the_race_removes_the_copies_and_starts_again_with_new_numbers(self):
        self.make_manifest()
        real_run = runner.run
        state = {"done": False}

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and not state["done"] and Path(repo) == self.a:
                state["done"] = True
                with self.user("Bea"):
                    create.new_part(self.b, "Bea's part")                  # Bea takes HCR-00002-001
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(runner, "run", run):
                result = self.run_import()
            self.assertEqual(sorted(result.pns), [PN("HCR", n, 1) for n in range(3, 7)])
            names = self.cad_names()
            self.assertNotIn("HCR-00002-001_A.SLDASM", names)                # nothing under the lost numbers
            self.assertFalse(any(n.startswith("HCR-00002") for n in names))
            self.assertEqual(len(self.fake.copied), 10)                    # copied twice
            self.assertEqual(record_store.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")   # her record was left alone
            # and the references inside point at the final names
            top = next(pn for pn in result.pns if record_store.load(self.a, pn).name == "top")
            for line in (self.a / "cad" / f"{top}_A.SLDASM").read_text().splitlines():
                if line.startswith("ref: "):
                    self.assertTrue(os.path.exists(line[5:]), line)
                    self.assertNotIn("HCR-00002", line)
            self.assert_clean(self.a)

    # -- crashes -----------------------------------------------------------
    def test_a_crash_while_copying_is_cleaned_up_by_the_next_import(self):
        self.make_manifest()
        leftovers = ["cad/HCR-00002-001_A.SLDPRT", "cad/HCR-00003-001_A.SLDASM"]
        for rel in leftovers:
            (self.a / rel).write_text("half copied")
        import_journal.write_journal(self.a, "copying", "tok1", leftovers, ["PN-logs/HCR-00002-001.yaml"])
        with self.user("Alex"):
            result = self.run_import()
            self.assertEqual(sorted(result.pns), [PN("HCR", n, 1) for n in range(2, 6)])
            self.assertFalse(any("half copied" in (self.a / "cad" / n).read_text() for n in self.cad_names()
                                 if n.startswith("HCR-0000") and n not in ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW")))
            self.assert_clean(self.a)

    def test_recover_removes_a_commit_that_was_never_pushed(self):
        with self.user("Alex"):
            rel_file, rel_record = "cad/HCR-00002-001_A.SLDPRT", "PN-logs/HCR-00002-001.yaml"
            (self.a / rel_file).write_text("copy")
            record_store.create_record(self.a, PN("HCR", 2, 1), "Crashed", "Alex")
            import_journal.write_journal(self.a, "committing", "tok2", [rel_file], [rel_record])
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Imported crash\n\nLitterbox-Import: tok2")
            self.assertEqual(import_journal.recover(self.a, lambda *_: None), "cleaned")
            self.assert_nothing_left()
            self.assertEqual(import_journal.recover(self.a, lambda *_: None), "nothing")

    def test_recover_keeps_an_import_that_was_actually_pushed(self):
        with self.user("Alex"):
            rel_file, rel_record = "cad/HCR-00002-001_A.SLDPRT", "PN-logs/HCR-00002-001.yaml"
            (self.a / rel_file).write_text("copy")
            record_store.create_record(self.a, PN("HCR", 2, 1), "Done", "Alex")
            import_journal.write_journal(self.a, "committing", "tok3", [rel_file], [rel_record])
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Imported done\n\nLitterbox-Import: tok3")
            git(self.a, "push")
            self.assertEqual(import_journal.recover(self.a, lambda *_: None), "finished")
            self.assertTrue((self.a / rel_file).exists())
            self.assert_clean(self.a)

    def test_recover_will_not_delete_outside_the_cad_folder(self):
        import_journal.write_journal(self.a, "copying", "x", ["PN-logs/HCR-00001-001.yaml"], [])
        with self.assertRaises(import_errors.ImportFailed):
            import_journal.recover(self.a, lambda *_: None)
        self.assertTrue((self.a / "PN-logs/HCR-00001-001.yaml").exists())

    def test_existing_cad_files_are_never_overwritten(self):
        self.make_manifest()
        (self.a / "cad" / "HCR-00002-001_A.SLDASM").write_text("a stray file someone dropped here")
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("will not overwrite", str(ctx.exception))
            self.assertEqual((self.a / "cad" / "HCR-00002-001_A.SLDASM").read_text(), "a stray file someone dropped here")

    # -- references outside the import ---------------------------------------
    def test_references_to_files_outside_the_import_are_refused_unless_allowed(self):
        self.make_manifest()
        mf = manifest.load(self.manifest_path)
        for item in mf.items:
            if item.name == "p1":
                item.include = False
        manifest.save(mf, self.manifest_path)
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("not part of this import", str(ctx.exception))
            self.assertIn("p1.SLDPRT", str(ctx.exception))
            self.assert_nothing_left()
            result = self.run_import(allow_external=True)
            self.assertEqual(len(result.pns), 3)
            self.assertTrue(any("outside the import" in w for w in result.warnings))
            sub = next(pn for pn in result.pns if record_store.load(self.a, pn).name == "sub")
            self.assertIn(str(self.src / "parts" / "p1.SLDPRT"), (self.a / "cad" / f"{sub}_A.SLDASM").read_text())

    def test_a_second_import_points_at_parts_imported_the_first_time(self):
        self.make_manifest()
        mf = manifest.load(self.manifest_path)
        for item in mf.items:
            item.include = item.name in ("p1", "p3")
        manifest.save(mf, self.manifest_path)
        with self.user("Alex"):
            first = self.run_import()
            mf = manifest.load(self.manifest_path)
            for item in mf.items:
                item.include = item.name in ("sub", "top")
            manifest.save(mf, self.manifest_path)
            second = self.run_import()
            sub = next(pn for pn in second.pns if record_store.load(self.a, pn).name == "sub")
            p3 = next(pn for pn in first.pns if record_store.load(self.a, pn).name == "p3")
            self.assertIn(str(self.a / "cad" / f"{p3}_A.SLDPRT"), (self.a / "cad" / f"{sub}_A.SLDASM").read_text())

    def test_bad_manifests_and_missing_files_stop_before_anything_happens(self):
        self.make_manifest()
        mf = manifest.load(self.manifest_path)
        mf.items[0].name = ""
        manifest.save(mf, self.manifest_path)
        with self.user("Alex"):
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("has no name", str(ctx.exception))
            mf.items[0].name = "fixed"
            manifest.save(mf, self.manifest_path)
            (self.src / "parts" / "p3.SLDPRT").unlink()
            with self.assertRaises(import_errors.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("can't be found", str(ctx.exception))
            self.assert_nothing_left()

    def test_a_reference_to_a_missing_file_is_only_a_warning(self):
        self.write("parts/p3.SLDPRT", ["ghost.SLDPRT"], stale={"ghost.SLDPRT": "/gone/ghost.SLDPRT"})
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import()
        self.assertTrue(any("ghost.SLDPRT" in w for w in result.warnings))

    # -- proposing, editing and checking part numbers --------------------------
    def prepare(self, **kwargs):
        kwargs.setdefault("gap", 0)
        kwargs.setdefault("backend", self.fake)
        kwargs.setdefault("log", lambda *_: None)
        return import_prepare.prepare(self.a, self.manifest_path, **kwargs)

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

    def assert_nothing_left_but_import(self, result):
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertFalse((self.a / ".git" / import_journal.JOURNAL_NAME).exists())

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
