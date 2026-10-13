"""
Tests for import_session.py and the table-editing parts of importer.py that the Import window uses.

The session runs jobs on a background thread and hands results back through `post`; here `post`
puts them on a queue and the test plays the part of the window, pumping that queue.

Run from the app folder with:  python -m unittest discover -s tests -v
"""

import queue
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_importer import ImportFixture  # noqa: E402
from vault_fixture import SKIP_ON_WINDOWS  # noqa: E402

import gui_logic as logic  # noqa: E402
import config  # noqa: E402
import import_session  # noqa: E402
import importer  # noqa: E402
import manifest  # noqa: E402
import registry  # noqa: E402
from pn import PN  # noqa: E402


@SKIP_ON_WINDOWS
class SessionFlow(ImportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.window = queue.Queue()
        self.threads_seen = set()
        self.session = import_session.ImportSession(
            self.a, self.window.put, backend_factory=lambda: self.fake, gap=0, jitter=0)
        self.addCleanup(self.stop_session)

    def stop_session(self):
        self.session.close()
        self.session._thread.join(5)

    def wait(self, start):
        """Start a job and pump the 'window' queue until its on_done arrives. Returns (result, error, progress)."""
        outcome, progress = {}, []

        def on_done(result, error):
            outcome["value"] = (result, error)

        start(on_done, progress.append)
        while "value" not in outcome:
            self.window.get(timeout=30)()
        result, error = outcome["value"]
        return result, error, progress

    def go(self, **kwargs):
        with self.user("Alex"):
            return self.wait(lambda done, prog: self.session.start(
                done, lambda *a: prog(a), manifest_root=self.tmp / "settings", **kwargs))

    # -- starting --------------------------------------------------------------
    def test_scanning_folders_saves_a_manifest_and_proposes_a_table(self):
        proposal, error, progress = self.go(folders=[self.src])
        self.assertIsNone(error)
        self.assertEqual(len(proposal.entries), 4)
        self.assertTrue(any("Scanning" in p[2] for p in progress))
        self.assertTrue(any("Reading references" in p[2] for p in progress))
        self.assertTrue(Path(self.session.manifest_path).exists())
        self.assertEqual(Path(self.session.manifest_path).parent, self.tmp / "settings" / "imports")
        self.assert_nothing_left()

    def test_an_existing_manifest_can_be_opened(self):
        self.make_manifest()
        proposal, error, _ = self.go(manifest_path=str(self.manifest_path))
        self.assertIsNone(error)
        self.assertEqual([e.name for e in proposal.entries], ["sub", "top", "p1", "p3"])

    def test_nothing_to_do_is_an_error_not_a_crash(self):
        with self.assertRaises(importer.ImportFailed):
            self.session.start(None)
        _, error, _ = self.go(manifest_path=str(self.tmp / "missing.yaml"))
        self.assertIsInstance(error, importer.ImportFailed)

    def test_all_the_slow_work_happens_on_one_thread_that_is_not_the_windows(self):
        seen = set()
        real_refs, real_copy = self.fake.references, self.fake.copy
        self.fake.references = lambda p: (seen.add(threading.get_ident()), real_refs(p))[1]
        self.fake.copy = lambda s, d: (seen.add(threading.get_ident()), real_copy(s, d))[0]
        self.go(folders=[self.src])
        with self.user("Alex"):
            _, error, _ = self.wait(lambda done, prog: self.session.finish(done, lambda *a: prog(a)))
        self.assertIsNone(error)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(threading.get_ident(), seen)

    # -- ticking rows ----------------------------------------------------------
    def entry_names(self):
        return [e.name for e in self.session.prepared.proposal.entries]

    def id_of(self, name):
        return next(i.id for i in self.session.prepared.candidates if i.name == name)

    def test_unticking_removes_the_row_and_ticking_puts_it_back_in_order(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            _, error, _ = self.wait(lambda d, p: self.session.include(self.id_of("sub"), False, d))
            self.assertIsNone(error)
            self.assertEqual(self.entry_names(), ["top", "p1", "p3"])
            _, error, _ = self.wait(lambda d, p: self.session.include(self.id_of("sub"), True, d))
            self.assertEqual(self.entry_names(), ["sub", "top", "p1", "p3"])
            pns = self.session.prepared.proposal.pns()
            self.assertEqual(len(set(pns)), 4)

    def test_a_row_ticked_later_gets_a_free_number(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(self.id_of("p3"), False, d))
            self.session.prepared.proposal.set_pn(0, "HCR-00005-001")      # typed, right where the next automatic number would go
            self.wait(lambda d, p: self.session.include(self.id_of("p3"), True, d))
            pns = self.session.prepared.proposal.pns()
            self.assertEqual(len(set(pns)), len(pns))

    def test_unticked_rows_are_not_imported_and_a_reference_to_them_is_refused(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(self.id_of("p1"), False, d))
            _, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsInstance(error, importer.ImportFailed)
            self.assertIn("not part of this import", str(error))
            self.assertIsInstance(error, importer.ExternalReferences)
            self.assertEqual({Path(f).name for f, _ in error.references}, {"top.SLDASM", "sub.SLDASM"})
            self.assertIn("not being imported", logic.import_external_text(error))
            self.assert_nothing_left()
            self.session.set_allow_external(True)
            result, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsNone(error)
            self.assertEqual(len(result.pns), 3)

    def test_nothing_ticked_is_a_clear_error(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            for name in ("p1", "p3", "sub", "top"):
                self.wait(lambda d, p, n=name: self.session.include(self.id_of(n), False, d))
            _, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIn("Nothing is selected", str(error))

    # -- numbers and finishing ---------------------------------------------------
    def test_refresh_reports_typed_numbers_that_are_taken(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            self.session.prepared.proposal.set_pn(1, "HCR-00001-001")
            state, error, _ = self.wait(lambda d, p: self.session.refresh(d))
        self.assertIsNone(error)
        self.assertEqual([(c.index, c.manual) for c in state.conflicts], [(1, True)])

    def test_finish_refused_for_a_taken_typed_number_leaves_the_session_usable(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            table = self.session.prepared.proposal
            table.set_pn(1, "HCR-00001-001")
            _, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsInstance(error, importer.PNConflict)
            self.assertEqual([c.index for c in error.conflicts], [1])
            self.assertFalse(self.session.busy)
            table.set_pn(1, "HCR-00800-001")
            result, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsNone(error)
            self.assertIn(PN("HCR", 800, 1), result.pns)

    def test_cancel_while_copying_leaves_nothing_and_the_session_can_try_again(self):
        self.go(folders=[self.src])
        real_copy = self.fake.copy
        count = {"n": 0}

        def slow_copy(src, dst):
            real_copy(src, dst)
            count["n"] += 1
            if count["n"] == 2:
                self.session.cancel()            # the user presses Cancel
        self.fake.copy = slow_copy
        with self.user("Alex"):
            _, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsInstance(error, importer.ImportCancelled)
            self.assert_nothing_left()
            self.fake.copy = real_copy
            result, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
            self.assertIsNone(error)
            self.assertEqual(len(result.pns), 4)

    def test_cancel_during_the_scan_changes_nothing(self):
        real_walk = import_session.scan_module.scan

        def cancelling_scan(folders, repo=None, progress=None):
            self.session.cancel()
            return real_walk(folders, repo=repo, progress=progress)

        import_session.scan_module.scan = cancelling_scan
        self.addCleanup(setattr, import_session.scan_module, "scan", real_walk)
        _, error, _ = self.go(folders=[self.src])
        self.assertIsInstance(error, importer.ImportCancelled)
        self.assertFalse((self.tmp / "settings" / "imports").exists())
        self.assert_nothing_left()

    def test_a_second_job_while_busy_is_refused(self):
        gate = threading.Event()
        real_refs = self.fake.references
        self.fake.references = lambda p: (gate.wait(10), real_refs(p))[1]
        with self.user("Alex"):
            self.session.start(lambda *a: None, folders=[self.src], manifest_root=self.tmp / "settings")
            with self.assertRaises(importer.ImportFailed):
                self.session.refresh(None)
            gate.set()
            self.session.cancel()

    def test_closing_the_session_closes_solidworks(self):
        closed = []
        self.fake.close = lambda: closed.append(True)
        self.go(folders=[self.src])
        self.stop_session()
        self.assertEqual(closed, [True])

    # -- what the window shows and how edits behave --------------------------------
    def rows(self, conflicts=()):
        prepared = self.session.prepared
        return logic.import_rows(prepared.candidates, prepared.proposal, conflicts)

    def test_table_rows_show_numbers_types_and_state(self):
        self.go(folders=[self.src])
        rows = self.rows()
        self.assertEqual([r.name for r in rows], ["sub", "top", "p1", "p3"])
        self.assertTrue(all(r.ticked and r.tag == "ok" and r.pn.startswith("HCR-") for r in rows))
        self.assertEqual({r.name: (r.kind, r.files) for r in rows}["top"], ("Assembly", "SLDASM, SLDDRW"))
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(self.id_of("sub"), False, d))
        off = self.rows()[0]
        self.assertEqual((off.ticked, off.pn, off.tag), (False, "", "off"))

    def test_editing_cells(self):
        self.go(folders=[self.src])
        prepared = self.session.prepared
        top = self.id_of("top")
        edit = lambda column, text, item=top: logic.edit_import_cell(prepared, item, column, text)
        self.assertEqual(edit("name", "  Top   assembly "), "")
        self.assertEqual(edit("description", "my notes"), "")
        self.assertEqual(edit("pn", "HCR-00700-001"), "")
        row = next(r for r in self.rows() if r.item_id == top)
        self.assertEqual((row.name, row.description, row.pn, row.tag), ("Top assembly", "my notes", "HCR-00700-001", "typed"))
        self.assertIn("required", edit("name", "   "))
        self.assertIn("under", edit("name", "x" * 101))
        self.assertIn("under", edit("description", "x" * 501))
        self.assertIn("Row", edit("pn", "banana"))
        self.assertEqual(edit("pn", ""), "")                                  # cleared: automatic again
        self.assertEqual(next(r for r in self.rows() if r.item_id == top).tag, "ok")
        self.assertIn("can't be edited", edit("files", "x"))
        self.assertIn("can't be edited", logic.edit_import_cell(prepared, 9999, "name", "x"))
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(top, False, d))
        self.assertIn("Select the row first", edit("pn", "HCR-00800-001"))
        self.assertEqual(edit("name", "Renamed while unticked"), "")           # name and description still editable
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(top, True, d))
        self.assertEqual(next(r for r in self.rows() if r.item_id == top).name, "Renamed while unticked")

    def test_proposed_numbers_start_at_the_start_number(self):
        config.save(self.a, org="HCR", start_number=10001)       # the vault also has HCR-00001-001, below the start
        with self.user("Alex"):
            self.make_manifest()
            prepared = importer.prepare(self.a, self.manifest_path, backend=self.fake, gap=0, jitter=0,
                                        log=lambda *_: None)
            self.assertEqual([p.base for p in prepared.proposal.pns()], list(range(10001, 10005)))
            self.assertIn("start number is 10001", prepared.proposal.note)
            self.assertIn("highest part number in use is 00001", prepared.proposal.note)
            self.assertIn("start_number is 10001", prepared.proposal.note)
            # a number freed up by a conflict, or a row ticked later, also comes from the same sequence
            top = prepared.candidates[0]
            importer.set_included(self.a, prepared, top.id, False)
            importer.set_included(self.a, prepared, top.id, True)
            self.assertTrue(all(p.base >= 10001 for p in prepared.proposal.pns()))

    def test_the_note_says_why_the_start_number_is_1(self):
        explain = config.explain_start_number
        self.assertIn("no settings file", explain(self.a))
        (self.a / "config.yaml").write_text("start_number: 10001\n")
        self.assertIn("does not read", explain(self.a))
        (self.a / ".litterbox").mkdir()
        (self.a / ".litterbox" / "config.yaml").write_text("org: HCR\nstarting_number: 10001\n")
        self.assertIn("rename it to start_number", explain(self.a))
        (self.a / ".litterbox" / "config.yaml").write_text("org: HCR\nstart_number: 10001\n")
        self.assertIn("start_number is 10001", explain(self.a))

    def test_cots_import_records_every_part_as_purchased(self):
        self.make_manifest()
        with self.user("Alex"):
            result = self.run_import(cots=True)
            records = [registry.load(self.a, pn) for pn in result.pns]
            self.assertTrue(all(r.cots and r.imported for r in records))
            self.assertIn("Imported 4 COTS parts", self.remote_log()[0])
            self.assertEqual(self.status_of(self.a, result.pns[0]).cots, True)

    def test_duplicate_finder(self):
        with self.user("Alex"):
            self.make_manifest()
            self.run_import()                                      # everything is now in the vault
            other = self.tmp / "other"
            other.mkdir()
            (other / "same_bytes.SLDPRT").write_bytes((self.src / "parts" / "p1.SLDPRT").read_bytes())
            (other / "p3.SLDPRT").write_text("different contents\n")
            (other / "new_a.SLDPRT").write_text("new\n")
            (other / "new_b.SLDPRT").write_text("new\n")
            (other / "unique.SLDPRT").write_text("unique\n")
            path = self.tmp / "other-manifest.yaml"
            manifest.save(import_session.scan_module.scan([other], repo=self.a), path)
            prepared = importer.prepare(self.a, path, backend=self.fake, gap=0, jitter=0, log=lambda *_: None, cots=True)
            names = [e.name for e in prepared.proposal.entries]
            found = importer.find_duplicates(self.a, prepared)
        row = {n: names.index(n) for n in names}
        self.assertIn("identical to the one in the vault", found[row["same bytes"]][0])
        self.assertTrue(any("exactly this name already exists" in w for w in found[row["p3"]]))
        self.assertTrue(any("identical" in w for w in found[row["p3"]]) is False)      # same name, different contents
        self.assertTrue(any("same file" in w for w in found[row["new a"]]))
        self.assertTrue(any("same file" in w for w in found[row["new b"]]))
        self.assertNotIn(row["unique"], found)
        self.assertEqual(prepared.cots, True)

    def test_cots_confirmation_text(self):
        text = logic.import_cots_confirm_text(3, {1: ["The file is identical to the one in the vault for HCR-00002-001."]},
                                              ["a", "bolt", "c"])
        self.assertIn("3 parts", text)
        self.assertIn("Row 2, bolt", text)
        self.assertIn("NOT", text.upper())
        self.assertNotIn("already has", logic.import_cots_confirm_text(1, {}, ["a"]))

    def test_part_number_boxes(self):
        self.go(folders=[self.src])
        prepared = self.session.prepared
        top = self.id_of("top")
        pn_of = lambda: next(e.pn for e in prepared.proposal.entries if e.item.id == top)
        edit = lambda base, variant, **k: logic.edit_import_pn(prepared, top, base, variant, **k)
        self.assertEqual(edit("00700", "002"), "")
        self.assertEqual(pn_of(), PN("HCR", 700, 2))
        self.assertEqual(edit("00700", ""), "")                       # empty variant: 001 without a repo...
        self.assertEqual(pn_of(), PN("HCR", 700, 1))
        self.assertEqual(edit("00001", "", repo=self.a), "")           # ...or the lowest free one (001 is taken)
        self.assertEqual(pn_of(), PN("HCR", 1, 2))
        self.assertEqual(edit("", "005"), "")                          # empty base keeps the base
        self.assertEqual(pn_of(), PN("HCR", 1, 5))
        self.assertIn("exactly 5 digits", edit("7", "001"))
        self.assertIn("exactly 3 digits", edit("00700", "1"))
        self.assertIn("can't be 00000", edit("00000", "001"))
        self.assertEqual(edit("", ""), "")                             # both empty: automatic again
        self.assertEqual(next(r for r in self.rows() if r.item_id == top).tag, "ok")
        auto = pn_of()
        self.assertEqual(edit(f"{auto.base:05d}", f"{auto.variant:03d}"), "")     # unchanged stays automatic
        self.assertEqual(next(r for r in self.rows() if r.item_id == top).tag, "ok")
        with self.user("Alex"):
            self.wait(lambda d, p: self.session.include(top, False, d))
        self.assertIn("Select the row first", edit("00700", "001"))
        self.assertIn("can't be edited", logic.edit_import_pn(prepared, 9999, "00700", "001"))

    def test_conflict_rows_are_marked_and_explained(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            self.session.prepared.proposal.set_pn(2, "HCR-00001-001")
            _, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
        rows = self.rows(error.conflicts)
        self.assertEqual([r.tag for r in rows], ["ok", "ok", "conflict", "ok"])
        self.assertIn("Front upright", rows[2].detail)
        text = logic.import_conflict_text(error.conflicts, [(0, None, None)])
        self.assertIn("Row 3", text)
        self.assertIn("Nothing was imported", text)
        self.assertIn("1 automatic", text)
        self.assertIn("1 part number", logic.import_summary_line(
            self.session.prepared.candidates, self.session.prepared.proposal, error.conflicts))

    def test_warnings_show_in_the_notes_column(self):
        self.write("parts/p3.SLDPRT", ["ghost.SLDPRT"], stale={"ghost.SLDPRT": "/gone/ghost.SLDPRT"})
        mf = self.src / "Old stuff"
        mf.mkdir()
        (mf / "spare.SLDPRT").write_text("model spare\n")
        self.go(folders=[self.src])
        spare = next(r for r in self.rows() if r.name == "spare")
        self.assertEqual(spare.tag, "warn")
        self.assertTrue(spare.notes)
        self.assertIn("spare.SLDPRT", spare.detail)

    def test_result_text(self):
        self.go(folders=[self.src])
        with self.user("Alex"):
            result, error, _ = self.wait(lambda d, p: self.session.finish(d, None))
        text = logic.import_result_text(result)
        self.assertIn("Imported 4 parts", text)
        self.assertIn("5 CAD file(s)", text)

    def test_default_manifest_path(self):
        from datetime import datetime
        path = import_session.default_manifest_path("/x", datetime(2026, 10, 9, 21, 7, 5))
        self.assertEqual(path, Path("/x/imports/import-20261009-210705.yaml"))


if __name__ == "__main__":
    unittest.main()
