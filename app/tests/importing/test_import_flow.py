"""Tests for importing: copying, renaming, repointing and committing, and cancelling cleanly. They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import os
import unittest
from tests.support.vault_fixture import SKIP_ON_WINDOWS, is_writable
from litterbox.importing import import_errors
from litterbox.importing import import_journal
from litterbox.importing import manifest
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.parts import get_latest
from tests.support.import_flow_fixture import ImportFlowFixture


@SKIP_ON_WINDOWS
class ImportFlow(ImportFlowFixture, unittest.TestCase):
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
            self.assertEqual({name: pn.variant for name, pn in by_name.items()},
                             {"p1": 1, "p3": 1, "sub": 500, "top": 500})          # assemblies: as New Assembly
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

    def test_step_and_pdf_exports_come_along_as_plain_copies(self):
        (self.src / "parts" / "p1.STEP").write_bytes(b"\xff\xfe a STEP file, not a SolidWorks document")
        (self.src / "top.pdf").write_bytes(b"%PDF-1.7 \xff\xfe")
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import()
            by_name = {record_store.load(self.a, pn).name: pn for pn in result.pns}
            cad = self.a / "cad"
            self.assertEqual((cad / f"{by_name['p1']}_A.STEP").read_bytes(), b"\xff\xfe a STEP file, not a SolidWorks document")
            self.assertEqual((cad / f"{by_name['top']}_A.PDF").read_bytes(), b"%PDF-1.7 \xff\xfe")
            self.assertFalse(any(path.endswith((".STEP", ".PDF")) for path in self.fake.copied))   # not via SolidWorks
            self.assert_clean(self.a)

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
            self.assertEqual(sorted(result.pns), [PN("HCR", 2, 500), PN("HCR", 3, 500), PN("HCR", 4, 1), PN("HCR", 5, 1)])
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


if __name__ == "__main__":
    unittest.main()
