"""Tests that a failed or crashed import leaves nothing behind (recover), and what stops an import before it starts. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import os
import unittest
from pathlib import Path
from unittest import mock
from tests.support.vault_fixture import SKIP_ON_WINDOWS, git
from litterbox.parts import create
from litterbox.importing import import_errors
from litterbox.importing import import_journal
from litterbox.importing import manifest
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.git import runner
from tests.support.import_flow_fixture import ImportFlowFixture


@SKIP_ON_WINDOWS
class ImportFailures(ImportFlowFixture, unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
