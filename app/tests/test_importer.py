"""
Tests for importer.py, using a pretend SolidWorks (files that are text with 'ref: <path>' lines)
and the same two-user vault as the create tests. They need Linux, macOS or WSL.

The important ones are the "leaves nothing behind" tests: cancelling, failing, losing a race for
the numbers, and crashing must each leave the vault and its git exactly as they were.

Run from the app folder with:  python -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
import shutil
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git, is_writable  # noqa: E402

import create  # noqa: E402
import importer  # noqa: E402
import litterbox_engine as eng  # noqa: E402
import manifest  # noqa: E402
import registry  # noqa: E402
import scan  # noqa: E402
from pn import PN  # noqa: E402


class FakeSolidWorks:
    """Stands in for SolidWorks. A 'document' is text; each line 'ref: <path>' is one reference."""

    def __init__(self, search_folder):
        self.search_folder = Path(search_folder)
        self.copied = []
        self.fail_on = None            # file name that makes copy() raise
        self.refuse_repoint = False

    @staticmethod
    def refs_in(path):
        with open(path, encoding="utf-8") as f:
            return [line[5:].strip() for line in f.read().splitlines() if line.startswith("ref: ")]

    def find(self, stored):
        if os.path.exists(stored):
            return stored
        hits = [p for p in self.search_folder.rglob("*") if p.is_file() and p.name.lower() == os.path.basename(stored).lower()]
        return str(hits[0]) if len(hits) == 1 else ""

    def references(self, path):
        stored = self.refs_in(path)
        return list(zip(stored, [self.find(s) for s in stored]))

    def copy(self, src, dst):
        if self.fail_on and os.path.basename(src) == self.fail_on:
            raise RuntimeError("simulated SolidWorks failure")
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data)
        self.copied.append(dst)

    def repoint(self, file, old, new):
        if self.refuse_repoint:
            return False
        with open(file, encoding="utf-8") as f:
            text = f.read()
        if f"ref: {old}" not in text:
            return False
        with open(file, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace(f"ref: {old}", f"ref: {new}"))
        return True

    def version(self):
        return "32.1"

    def close(self):
        pass


@SKIP_ON_WINDOWS
class ImportFixture(TwoUserVault):
    """A vault, a pretend SolidWorks and an old CAD folder (top.SLDASM + drawing, sub.SLDASM, p1, p3). No tests here."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = self.tmp / "old cad"
        (self.src / "parts").mkdir(parents=True)
        self.write("parts/p1.SLDPRT", [])
        self.write("parts/p3.SLDPRT", [])
        self.write("sub.SLDASM", ["p3.SLDPRT", "p1.SLDPRT"])
        self.write("top.SLDASM", ["sub.SLDASM", "p1.SLDPRT"], stale={"sub.SLDASM": "/gone/folder/sub.SLDASM"})
        self.write("top.SLDDRW", ["top.SLDASM"])
        self.fake = FakeSolidWorks(self.src)
        self.manifest_path = self.tmp / "manifest.yaml"

    # -- helpers -----------------------------------------------------------
    def write(self, relative, refs, stale=None):
        path = self.src / relative
        lines = [f"model {relative}"]
        for ref in refs:
            target = (stale or {}).get(ref) or str(next(self.src.rglob(ref), self.src / ref))
            lines.append(f"ref: {target}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def make_manifest(self, repo=None):
        manifest.save(scan.scan([self.src], repo=repo or self.a), self.manifest_path)

    def originals(self):
        return {str(p): p.read_bytes() for p in self.src.rglob("*") if p.is_file()}

    def run_import(self, **kwargs):
        kwargs.setdefault("backend", self.fake)
        kwargs.setdefault("log", lambda *_: None)
        kwargs.setdefault("gap", 0)                    # numbers right after the last one, to keep these tests simple
        return importer.run(self.a, self.manifest_path, **kwargs)

    def assert_clean(self, repo):
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(git(repo, "rev-list", "--count", "@{u}..HEAD"), "0")

    def cad_names(self, repo=None):
        return sorted(p.name for p in ((repo or self.a) / "cad").iterdir())

    def assert_nothing_left(self):
        self.assertEqual(self.cad_names(), ["HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.SLDPRT"])
        self.assertEqual(sorted(p.name for p in (self.a / "PN-logs").iterdir()), ["HCR-00001-001.yaml"])
        self.assert_clean(self.a)
        self.assertFalse((self.a / ".git" / importer.JOURNAL_NAME).exists())


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
            by_name = {registry.load(self.a, pn).name: pn for pn in result.pns}
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
            record = registry.load(self.a, top)
            self.assertTrue(record.imported)
            self.assertFalse(record.cots)
            self.assertEqual(record.description, "top.SLDASM, top.SLDDRW")
            self.assertEqual(record.import_path, str(self.src / "top.SLDASM"))
            # one commit, one push, nothing pending, read-only, no journal, manifest updated
            self.assertEqual(len(self.remote_log()), commits + 1)
            self.assertIn("Imported 4 parts", self.remote_log()[0])
            self.assert_clean(self.a)
            self.assertFalse(is_writable(cad / f"{top}_A.SLDASM"))
            self.assertFalse((self.a / ".git" / importer.JOURNAL_NAME).exists())
            self.assertEqual(sorted(i.pn for i in manifest.load(self.manifest_path).items), sorted(map(str, result.pns)))
            # the status list shows them as ordinary parts with files
            self.assertEqual(self.status_of(self.a, top).kind, "ok")
        with self.user("Bea"):
            eng.get_latest(self.b)
            self.assertTrue((self.b / "cad" / f"{top}_A.SLDASM").exists())

    def test_running_it_again_has_nothing_to_do(self):
        self.make_manifest()
        with self.user("Alex"):
            self.run_import()
            with self.assertRaises(importer.ImportFailed) as ctx:
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
            with self.assertRaises(importer.ImportCancelled):
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

            with self.assertRaises(importer.ImportCancelled):
                self.run_import(cancel=cancel)
            self.assertEqual(len(self.fake.copied), 5)
            self.assert_nothing_left()
            self.assertEqual(self.remote_log()[0], "Start vault")

    def test_cancel_before_anything_starts(self):
        self.make_manifest()
        with self.user("Alex"):
            with self.assertRaises(importer.ImportCancelled):
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
            with self.assertRaises(importer.ImportFailed) as ctx:
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
        real_run = eng.run

        def broken(command, repo, quiet=False):
            if command[:2] == ["git", "push"]:
                raise eng.LitterboxError("simulated network failure")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(eng, "run", broken):
                with self.assertRaises(eng.LitterboxError):
                    self.run_import()
            self.assert_nothing_left()
            self.assertEqual(len(self.run_import().pns), 4)

    def test_offline_at_the_start_changes_nothing(self):
        self.make_manifest()
        real_run = eng.run

        def offline(command, repo, quiet=False):
            if command[:2] == ["git", "pull"]:
                raise eng.LitterboxError("simulated: no connection")
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(eng, "run", offline):
                with self.assertRaises(importer.ImportFailed):
                    self.run_import()
            self.assertEqual(self.fake.copied, [])
            self.assert_nothing_left()

    # -- someone else gets the numbers first --------------------------------
    def test_losing_the_race_removes_the_copies_and_starts_again_with_new_numbers(self):
        self.make_manifest()
        real_run = eng.run
        state = {"done": False}

        def run(command, repo, quiet=False):
            if command[:2] == ["git", "push"] and not state["done"] and Path(repo) == self.a:
                state["done"] = True
                with self.user("Bea"):
                    create.new_part(self.b, "Bea's part")                  # Bea takes HCR-00002-001
            return real_run(command, repo, quiet)

        with self.user("Alex"):
            with mock.patch.object(eng, "run", run):
                result = self.run_import()
            self.assertEqual(sorted(result.pns), [PN("HCR", n, 1) for n in range(3, 7)])
            names = self.cad_names()
            self.assertNotIn("HCR-00002-001_A.SLDASM", names)                # nothing under the lost numbers
            self.assertFalse(any(n.startswith("HCR-00002") for n in names))
            self.assertEqual(len(self.fake.copied), 10)                    # copied twice
            self.assertEqual(registry.load(self.a, PN("HCR", 2, 1)).created_by, "Bea")   # her record was left alone
            # and the references inside point at the final names
            top = next(pn for pn in result.pns if registry.load(self.a, pn).name == "top")
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
        importer._write_journal(self.a, "copying", "tok1", leftovers, ["PN-logs/HCR-00002-001.yaml"])
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
            registry.create_record(self.a, PN("HCR", 2, 1), "Crashed", "Alex")
            importer._write_journal(self.a, "committing", "tok2", [rel_file], [rel_record])
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Imported crash\n\nLitterbox-Import: tok2")
            self.assertEqual(importer.recover(self.a, lambda *_: None), "cleaned")
            self.assert_nothing_left()
            self.assertEqual(importer.recover(self.a, lambda *_: None), "nothing")

    def test_recover_keeps_an_import_that_was_actually_pushed(self):
        with self.user("Alex"):
            rel_file, rel_record = "cad/HCR-00002-001_A.SLDPRT", "PN-logs/HCR-00002-001.yaml"
            (self.a / rel_file).write_text("copy")
            registry.create_record(self.a, PN("HCR", 2, 1), "Done", "Alex")
            importer._write_journal(self.a, "committing", "tok3", [rel_file], [rel_record])
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Imported done\n\nLitterbox-Import: tok3")
            git(self.a, "push")
            self.assertEqual(importer.recover(self.a, lambda *_: None), "finished")
            self.assertTrue((self.a / rel_file).exists())
            self.assert_clean(self.a)

    def test_recover_will_not_delete_outside_the_cad_folder(self):
        importer._write_journal(self.a, "copying", "x", ["PN-logs/HCR-00001-001.yaml"], [])
        with self.assertRaises(importer.ImportFailed):
            importer.recover(self.a, lambda *_: None)
        self.assertTrue((self.a / "PN-logs/HCR-00001-001.yaml").exists())

    def test_existing_cad_files_are_never_overwritten(self):
        self.make_manifest()
        (self.a / "cad" / "HCR-00002-001_A.SLDASM").write_text("a stray file someone dropped here")
        with self.user("Alex"):
            with self.assertRaises(importer.ImportFailed) as ctx:
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
            with self.assertRaises(importer.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("not part of this import", str(ctx.exception))
            self.assertIn("p1.SLDPRT", str(ctx.exception))
            self.assert_nothing_left()
            result = self.run_import(allow_external=True)
            self.assertEqual(len(result.pns), 3)
            self.assertTrue(any("outside the import" in w for w in result.warnings))
            sub = next(pn for pn in result.pns if registry.load(self.a, pn).name == "sub")
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
            sub = next(pn for pn in second.pns if registry.load(self.a, pn).name == "sub")
            p3 = next(pn for pn in first.pns if registry.load(self.a, pn).name == "p3")
            self.assertIn(str(self.a / "cad" / f"{p3}_A.SLDPRT"), (self.a / "cad" / f"{sub}_A.SLDASM").read_text())

    def test_bad_manifests_and_missing_files_stop_before_anything_happens(self):
        self.make_manifest()
        mf = manifest.load(self.manifest_path)
        mf.items[0].name = ""
        manifest.save(mf, self.manifest_path)
        with self.user("Alex"):
            with self.assertRaises(importer.ImportFailed) as ctx:
                self.run_import()
            self.assertIn("has no name", str(ctx.exception))
            mf.items[0].name = "fixed"
            manifest.save(mf, self.manifest_path)
            (self.src / "parts" / "p3.SLDPRT").unlink()
            with self.assertRaises(importer.ImportFailed) as ctx:
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
        kwargs.setdefault("backend", self.fake)
        kwargs.setdefault("log", lambda *_: None)
        kwargs.setdefault("gap", 0)
        return importer.prepare(self.a, self.manifest_path, **kwargs)

    def test_proposed_numbers_start_a_gap_above_the_highest_in_use(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare(gap=100, jitter=0)
            self.assertEqual(prepared.proposal.pns(), [PN("HCR", n, 1) for n in range(101, 105)])
            prepared = self.prepare(gap=100, jitter=50)
            first = prepared.proposal.entries[0].pn.base
            self.assertTrue(101 <= first < 151)
            self.assertEqual([e.pn.base for e in prepared.proposal.entries], list(range(first, first + 4)))
            self.assert_nothing_left()                            # proposing writes nothing

    def test_starting_an_import_gets_the_newest_numbers_first(self):
        self.make_manifest()
        with self.user("Bea"):
            create.new_part(self.b, "Bea's new part")             # HCR-00002-001, pushed
        with self.user("Alex"):
            prepared = self.prepare(gap=100, jitter=0)
            self.assertEqual(prepared.proposal.entries[0].pn, PN("HCR", 102, 1))
            self.assertTrue((self.a / "PN-logs" / "HCR-00002-001.yaml").exists())

    def test_the_block_is_placed_in_the_gap_so_normal_new_parts_do_not_collide_with_it(self):
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import(gap=100, jitter=0)
            self.assertEqual(sorted(p.base for p in result.pns), [101, 102, 103, 104])
            self.assertEqual(create.new_part(self.a, "Ordinary part"), PN("HCR", 2, 1))    # gap still filled normally

    def test_names_descriptions_and_numbers_can_be_edited_before_finishing(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            table = prepared.proposal
            table.entries[0].name = "Renamed by hand"
            table.entries[0].description = "my notes"
            table.set_pn(1, "HCR-00500-002")
            result = importer.finish(self.a, prepared, log=lambda *_: None)
            prepared.close()
            self.assertEqual(result.pns[1], PN("HCR", 500, 2))
            self.assertTrue((self.a / "cad" / f"HCR-00500-002{Path(result.plan.order[0]).suffix}").exists()
                            or any(n.startswith("HCR-00500-002") for n in self.cad_names()))
            record = registry.load(self.a, result.pns[0])
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
            with self.assertRaises(importer.PNConflict) as ctx:
                importer.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([(c.index, c.manual) for c in ctx.exception.conflicts], [(2, True)])
            self.assertIn("Front upright", str(ctx.exception))
            self.assertEqual(self.fake.copied, [])                # refused before copying anything
            self.assert_nothing_left()
            self.assertEqual(prepared.proposal.entries[2].pn, PN("HCR", 1, 1))        # the typed number is untouched
            self.assertEqual([e.pn for e in prepared.proposal.entries if not e.manual],
                             [b for i, b in enumerate(before) if i != 2])
            prepared.proposal.set_pn(2, "HCR-00700-001")           # the user fixes the red row...
            result = importer.finish(self.a, prepared, log=lambda *_: None)    # ...and finishes again
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
            result = importer.finish(self.a, prepared, log=lambda *_: None)
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
            with self.assertRaises(importer.PNConflict) as ctx:
                importer.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [0])
            # the automatic rows were already moved on to free numbers, ready for the next try
            self.assertTrue(all(e.pn.base >= 4 for e in prepared.proposal.entries[1:]))
            prepared.proposal.reset_pn(0)                          # hand row 0 back to Litterbox
            result = importer.finish(self.a, prepared, log=lambda *_: None)
            prepared.close()
            self.assertEqual(len(set(result.pns)), 4)
            self.assert_nothing_left_but_import(result)

    def test_a_typed_number_taken_at_the_last_moment_is_reported_and_cleaned_up(self):
        self.make_manifest()
        real_run = eng.run
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
            with mock.patch.object(eng, "run", run):
                with self.assertRaises(importer.PNConflict) as ctx:
                    importer.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [1])
            self.assertEqual(self.cad_names(), ["HCR-00001-001_A.SLDDRW", "HCR-00001-001_A.SLDPRT"])
            self.assert_clean(self.a)
            prepared.proposal.set_pn(1, "HCR-00801-001")
            self.assertEqual(len(importer.finish(self.a, prepared, log=lambda *_: None).pns), 4)
            prepared.close()

    def test_the_same_number_twice_in_the_table_is_a_conflict(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(0, "HCR-00600-001")
            prepared.proposal.set_pn(1, "HCR-00600-001")
            with self.assertRaises(importer.PNConflict) as ctx:
                importer.finish(self.a, prepared, log=lambda *_: None)
            self.assertEqual([c.index for c in ctx.exception.conflicts], [1])
            self.assertIn("twice", str(ctx.exception))

    def test_bad_typed_numbers_are_rejected_when_typed(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            for text in ("", "banana", "HCR-00000-001", "HCR-00005-000", "HCR-5-1"):
                with self.assertRaises(importer.ImportFailed):
                    prepared.proposal.set_pn(0, text)
            prepared.proposal.set_pn(0, "XYZ-00600-001")           # a valid PN for another organization
            with self.assertRaises(importer.PNConflict) as ctx:
                importer.finish(self.a, prepared, log=lambda *_: None)
            self.assertIn("different organization", str(ctx.exception))

    def assert_nothing_left_but_import(self, result):
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertFalse((self.a / ".git" / importer.JOURNAL_NAME).exists())

    def test_cancelling_after_a_conflict_retry_still_leaves_nothing(self):
        self.make_manifest()
        with self.user("Alex"):
            prepared = self.prepare()
            prepared.proposal.set_pn(0, "HCR-00001-001")
            with self.assertRaises(importer.PNConflict):
                importer.finish(self.a, prepared, log=lambda *_: None)
            prepared.proposal.reset_pn(0)
            with self.assertRaises(importer.ImportCancelled):
                importer.finish(self.a, prepared, cancel=lambda: len(self.fake.copied) >= 2, log=lambda *_: None)
            prepared.close()
            self.assert_nothing_left()

    def test_command_line_dry_run_and_recover(self):
        self.make_manifest()
        with self.user("Alex"):
            with mock.patch.object(importer, "SolidWorksBackend", lambda: self.fake):
                self.assertEqual(importer.main([str(self.a), str(self.manifest_path), "--dry-run"]), 0)
                self.assertEqual(importer.main([str(self.a), "--recover"]), 0)
                self.assertEqual(importer.main([str(self.a), str(self.manifest_path)]), 0)
                self.assertEqual(importer.main([str(self.a), str(self.manifest_path)]), 1)     # nothing left to import


class PairReferences(unittest.TestCase):
    def test_lists_that_line_up_are_paired_by_position(self):
        self.assertEqual(importer.pair_references(["/old/a.SLDPRT", "/old/b.SLDPRT"], ["/x/a.SLDPRT", "/y/b.SLDPRT"]),
                         [("/old/a.SLDPRT", "/x/a.SLDPRT"), ("/old/b.SLDPRT", "/y/b.SLDPRT")])

    def test_lists_that_do_not_line_up_are_paired_by_unique_file_name(self):
        pairs = importer.pair_references(["/old/a.SLDPRT", "/old/c.SLDPRT"], ["/y/a.SLDPRT", "/z/a.SLDPRT", "/y/b.SLDPRT"])
        self.assertEqual(pairs, [("/old/a.SLDPRT", ""), ("/old/c.SLDPRT", "")])
        pairs = importer.pair_references(["/old/a.SLDPRT"], ["/y/a.SLDPRT", "/y/b.SLDPRT"])
        self.assertEqual(pairs, [("/old/a.SLDPRT", "/y/a.SLDPRT")])


if __name__ == "__main__":
    unittest.main()


class ClosingSolidWorks(unittest.TestCase):
    """The SolidWorks we start must really be gone afterwards, or Open later lands in an invisible window."""

    def test_waits_for_a_slow_exit_without_ending_it(self):
        alive = iter([True, True, False])
        ended = []
        result = importer.wait_for_exit(42, alive=lambda pid: next(alive), kill=ended.append, sleep=lambda s: None)
        self.assertEqual((result, ended), ("exited", []))

    def test_ends_a_process_that_will_not_exit(self):
        ended, notes = [], []
        result = importer.wait_for_exit(42, timeout=1, alive=lambda pid: True, kill=ended.append,
                                        sleep=lambda s: None, log=notes.append)
        self.assertEqual((result, ended), ("ended", [42]))
        self.assertTrue(notes)

    def test_already_gone_needs_no_waiting(self):
        self.assertEqual(importer.wait_for_exit(42, alive=lambda pid: False, kill=lambda p: 1 / 0), "exited")

    def test_only_a_solidworks_we_started_is_exited_and_waited_for(self):
        calls = []

        class App:
            def GetProcessID(self):
                return 77

            def ExitApp(self):
                calls.append("exit")

        original = importer.wait_for_exit
        importer.wait_for_exit = lambda pid, **kw: calls.append(("wait", pid))
        try:
            backend = importer.SolidWorksBackend()
            backend._sw, backend._started_by_us = App(), True
            backend.close()
            self.assertEqual(calls, ["exit", ("wait", 77)])
            calls.clear()
            backend._sw, backend._started_by_us, backend._pid = App(), True, 55     # learned at start-up: preferred
            backend.close()
            self.assertEqual(calls, ["exit", ("wait", 55)])
            calls.clear()
            backend._sw, backend._started_by_us = App(), False          # the user's own SolidWorks: hands off
            backend.close()
            self.assertEqual(calls, [])
        finally:
            importer.wait_for_exit = original


class CopyingWhenSolidWorksRefuses(unittest.TestCase):
    """SolidWorks sometimes refuses CopyDocument (it returned 2 for a McMaster washer). A lone part is copied as
    an ordinary file; anything else is reported."""

    def setUp(self):
        import sys
        import tempfile
        import types
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        fake_pythoncom = types.ModuleType("pythoncom")
        fake_pythoncom.VT_ARRAY, fake_pythoncom.VT_BSTR = 0x2000, 8
        client = types.ModuleType("win32com.client")
        client.VARIANT = lambda kind, value: value
        win32com = types.ModuleType("win32com")
        win32com.client = client
        for name, module in (("pythoncom", fake_pythoncom), ("win32com", win32com), ("win32com.client", client)):
            old = sys.modules.get(name)
            sys.modules[name] = module
            self.addCleanup(lambda n=name, o=old: sys.modules.pop(n, None) if o is None else sys.modules.update({n: o}))

    def backend(self, deps):
        class App:
            def CopyDocument(inner, *args):
                return 2                                    # refused, and nothing was written

        backend = importer.SolidWorksBackend()
        backend._sw = App()
        backend._dependencies = lambda path, search: deps
        return backend

    def test_a_lone_part_is_copied_as_a_file(self):
        src = self.dir / "washer.SLDPRT"
        src.write_bytes(b"washer")
        dst = self.dir / "vault" / "cad" / "HCR-00002-001_A.SLDPRT"
        self.backend([]).copy(str(src), str(dst))
        self.assertEqual(dst.read_bytes(), b"washer")

    def test_a_file_with_references_is_reported_not_copied_blindly(self):
        src = self.dir / "bracket.SLDASM"
        src.write_bytes(b"asm")
        dst = self.dir / "out" / "x.SLDASM"
        with self.assertRaises(importer.ImportFailed) as ctx:
            self.backend([]).copy(str(src), str(dst))
        self.assertIn("it returned 2", str(ctx.exception))
        self.assertFalse(dst.exists())
        part = self.dir / "uses.SLDPRT"
        part.write_bytes(b"p")
        with self.assertRaises(importer.ImportFailed):
            self.backend(["C:/other.SLDPRT"]).copy(str(part), str(self.dir / "out" / "y.SLDPRT"))


class FindingTheProcess(unittest.TestCase):
    def test_solidworks_own_answer_is_used(self):
        class App:
            def GetProcessID(self):
                return 9
        self.assertEqual(importer.own_process_id(App(), {1}), 9)

    def test_otherwise_the_one_new_process_is_used(self):
        class App:
            def GetProcessID(self):
                raise RuntimeError
        original = importer.solidworks_pids
        try:
            importer.solidworks_pids = lambda: {1, 8}
            self.assertEqual(importer.own_process_id(App(), {1}), 8)
            importer.solidworks_pids = lambda: {1, 8, 9}                     # two new: can't tell which
            self.assertIsNone(importer.own_process_id(App(), {1}))
        finally:
            importer.solidworks_pids = original

    def test_the_wait_is_five_seconds(self):
        self.assertEqual(importer.EXIT_WAIT_SECONDS, 5.0)
