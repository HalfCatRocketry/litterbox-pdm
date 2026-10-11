"""Tests for scan.py and manifest.py. Run from the app folder with:  python -m unittest discover -s tests -v"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import manifest as mf
import registry
import scan
from pn import PN


class ScanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.src = self.root / "old cad"
        self.src.mkdir()
        self.out = self.root / "out" / "manifest.yaml"

    def put(self, relative, content=b"data"):
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    def run_scan(self, **kwargs):
        return scan.scan([self.src], **kwargs)

    def by_name(self, result):
        return {item.name: item for item in result.items}

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.stat().st_mtime_ns, p.read_bytes())
                for p in sorted(self.root.rglob("*")) if p.is_file()}


class TestFinding(ScanTestCase):
    def test_parts_assemblies_and_drawings_are_found_and_paired(self):
        self.put("valves/valve_body.SLDPRT", "body")
        self.put("valves/valve_body.SLDDRW", "drawing")
        self.put("valves/valve_assy.SLDASM", "assembly")
        self.put("valves/valve_assy.slddrw", "assembly drawing")
        result = self.run_scan()
        items = self.by_name(result)
        self.assertEqual(sorted(items), ["valve assy", "valve body"])
        body = items["valve body"]
        self.assertEqual(body.kind, "part")
        self.assertEqual([f.type for f in body.files], ["SLDPRT", "SLDDRW"])        # the model first
        self.assertEqual(body.description, "valve_body.SLDPRT, valve_body.SLDDRW")  # old file names
        self.assertEqual(items["valve assy"].kind, "assembly")
        self.assertTrue(body.include)
        self.assertFalse(body.cots)
        self.assertEqual(result.stats["items"], 2)
        self.assertEqual(result.stats["files_to_import"], 4)

    def test_a_drawing_with_no_model_stands_alone_with_a_warning(self):
        self.put("misc/orphan.SLDDRW")
        item = self.run_scan().items[0]
        self.assertEqual((item.kind, len(item.files)), ("drawing", 1))
        self.assertTrue(any("No model" in w for w in item.warnings))

    def test_a_drawing_is_not_paired_when_two_models_share_its_name(self):
        self.put("x/thing.SLDPRT")
        self.put("x/thing.SLDASM")
        self.put("x/thing.SLDDRW")
        result = self.run_scan()
        self.assertEqual(sorted((i.kind, len(i.files)) for i in result.items),
                         [("assembly", 1), ("drawing", 1), ("part", 1)])
        drawing = next(i for i in result.items if i.kind == "drawing")
        self.assertTrue(any("More than one model" in w for w in drawing.warnings))

    def test_same_names_in_different_folders_are_different_items(self):
        self.put("a/bracket.SLDPRT", "one")
        self.put("b/bracket.SLDPRT", "two")
        self.assertEqual(len(self.run_scan().items), 2)

    def test_junk_and_other_files_are_not_items(self):
        self.put("a/part.SLDPRT")
        self.put("a/~$part.SLDPRT")
        self.put("a/part.SLDPRT.bak")
        self.put("a/old.tmp")
        self.put("a/notes.txt")
        self.put("a/photo.JPG")
        self.put("a/photo2.jpg")
        self.put(".git/config")
        self.put("swxauto/recover.SLDPRT")
        result = self.run_scan()
        self.assertEqual([i.name for i in result.items], ["part"])
        self.assertEqual(result.stats["skipped_junk_files"], 3)
        self.assertEqual(result.stats["other_files"], {".jpg": 2, ".txt": 1})

    def test_the_same_folder_listed_twice_or_nested_counts_once(self):
        self.put("a/part.SLDPRT")
        result = scan.scan([self.src, self.src, self.src / "a"])
        self.assertEqual(len(result.items), 1)

    def test_results_come_in_a_stable_order_with_numbered_ids(self):
        for name in ("zeta/z.SLDPRT", "alpha/b.SLDPRT", "alpha/a.SLDPRT"):
            self.put(name)
        result = self.run_scan()
        self.assertEqual([i.name for i in result.items], ["a", "b", "z"])
        self.assertEqual([i.id for i in result.items], [1, 2, 3])

    def test_bad_sources(self):
        with self.assertRaises(scan.ScanError):
            scan.scan([])
        with self.assertRaises(scan.ScanError):
            scan.scan([self.root / "nope"])
        self.put("file.SLDPRT")
        with self.assertRaises(scan.ScanError):
            scan.scan([self.src / "file.SLDPRT"])


class TestJudgements(ScanTestCase):
    def test_scan_never_guesses_cots(self):
        self.put("McMaster/screw.SLDPRT")
        self.put("hardware/Purchased Parts/nut.SLDPRT")
        self.put("misc/91251A540 bolt.SLDPRT")
        self.put("misc/Igniter COTS fittings.SLDASM")
        self.put("misc/own_bracket.SLDPRT")
        result = self.run_scan()
        self.assertFalse(any(i.cots for i in result.items))
        self.assertFalse(any("cots" in w.lower() for i in result.items for w in i.warnings))

    def test_words_must_match_whole_words_for_old_folder_warnings(self):
        self.put("Old designs/a.SLDPRT")
        self.put("Gold standard/b.SLDPRT")
        items = self.by_name(self.run_scan())
        self.assertTrue(any("'Old designs'" in w for w in items["a"].warnings))
        self.assertEqual(items["b"].warnings, [])

    def test_the_scan_folder_itself_is_not_judged_by_its_own_name(self):
        old = self.root / "Old CAD stuff"
        old.mkdir()
        (old / "a.SLDPRT").write_bytes(b"x")
        self.assertEqual(scan.scan([old]).items[0].warnings, [])

    def test_copy_looking_names_empty_files_and_long_names_are_flagged(self):
        self.put("a/bracket - Copy.SLDPRT", "x")
        self.put("a/bracket (2).SLDPRT", "y")
        self.put("a/empty.SLDPRT", b"")
        self.put("a/" + "long_" * 30 + ".SLDPRT", "z")
        items = self.by_name(self.run_scan())
        self.assertTrue(any("copy or a backup" in w for w in items["bracket - Copy"].warnings))
        self.assertTrue(any("copy or a backup" in w for w in items["bracket (2)"].warnings))
        self.assertTrue(any("empty" in w for w in items["empty"].warnings))
        long_item = next(i for n, i in items.items() if n.startswith("long long"))
        self.assertLessEqual(len(long_item.name), 100)
        self.assertTrue(any("shortened" in w for w in long_item.warnings))
        self.assertIn("long_long_", long_item.description)                  # the whole old name survives

    def test_very_long_paths_are_flagged(self):
        deep = "/".join(["folder_with_a_long_name"] * 11)
        self.put(f"{deep}/part.SLDPRT")
        item = self.run_scan().items[0]
        self.assertTrue(any("very long" in w for w in item.warnings))

    def test_exact_copies_are_reported_but_never_merged(self):
        self.put("a/valve.SLDPRT", "same bytes")
        self.put("b/valve.SLDPRT", "same bytes")
        self.put("c/valve.SLDPRT", "different")
        self.put("d/other.SLDPRT", "same bytes")
        result = self.run_scan()
        self.assertEqual(len(result.items), 4)                               # nothing merged
        ids = {Path(i.main_path).parent.name: i for i in result.items}
        self.assertEqual(ids["a"].identical_to, sorted([ids["b"].id, ids["d"].id]))
        self.assertEqual(ids["c"].identical_to, [])
        self.assertEqual(result.stats["groups_of_identical_files"], 1)
        self.assertEqual(result.stats["extra_identical_copies"], 2)
        self.assertEqual(result.stats["bytes_in_extra_copies"], 2 * len("same bytes"))
        self.assertTrue(all(len(i.include and i.files[0].sha256) == 64 for i in result.items))

    def test_no_hash_still_scans_but_has_no_copy_report(self):
        self.put("a/valve.SLDPRT", "x")
        self.put("b/valve.SLDPRT", "x")
        result = self.run_scan(hash_files=False)
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0].files[0].sha256, "")
        self.assertEqual(result.stats["groups_of_identical_files"], 0)
        self.assertIn("hashed", result.stats)
        self.assertNotIn("Exact copies", scan.format_report(result))

    @unittest.skipIf(not hasattr(os, "geteuid") or os.geteuid() == 0, "needs a normal user to deny read access")
    def test_an_unreadable_file_is_left_out_with_a_warning(self):
        path = self.put("a/locked.SLDPRT")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        item = self.run_scan().items[0]
        self.assertFalse(item.include)
        self.assertTrue(any("Could not read" in w for w in item.warnings))

    def test_progress_is_reported(self):
        self.put("a/x.SLDPRT")
        self.put("a/y.SLDPRT")
        calls = []
        self.run_scan(progress=lambda done, total, path: calls.append((done, total)))
        self.assertEqual(calls, [(1, 2), (2, 2)])


class TestAlreadyImported(ScanTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "vault"
        self.repo.mkdir()

    def test_files_imported_before_are_left_out_by_default(self):
        old = self.put("a/valve.SLDPRT", "v")
        self.put("a/new.SLDPRT", "n")
        registry.create_record(self.repo, PN("HCR", 5, 1), "valve", "Alex", imported=True, import_path=str(old))
        items = self.by_name(self.run_scan(repo=self.repo))
        self.assertFalse(items["valve"].include)
        self.assertEqual(items["valve"].already_imported_as, "HCR-00005-001")
        self.assertTrue(items["new"].include)
        self.assertEqual(self.run_scan(repo=self.repo).stats["already_imported"], 1)
        self.assertTrue(self.by_name(self.run_scan())["valve"].include)       # without --repo nothing is known

    def test_a_vault_inside_the_scanned_folder_is_not_scanned(self):
        inner = self.src / "vault"
        (inner / "cad").mkdir(parents=True)
        (inner / "cad" / "HCR-00001-001_A.SLDPRT").write_bytes(b"in the vault")
        self.put("a/mine.SLDPRT")
        self.assertEqual([i.name for i in scan.scan([self.src], repo=inner).items], ["mine"])


class TestNothingIsChanged(ScanTestCase):
    def test_scanning_and_saving_a_manifest_touch_nothing_in_the_source(self):
        self.put("a/valve.SLDPRT", "v")
        self.put("a/valve.SLDDRW", "d")
        self.put("McMaster/bolt.SLDPRT", "b")
        self.put("a/notes.txt", "n")
        os.chmod(self.src / "a" / "valve.SLDPRT", 0o444)                       # even read-only files are fine
        before = self.snapshot()
        mf.save(self.run_scan(), self.out)
        after = self.snapshot()
        self.assertEqual({k: v for k, v in after.items() if not k.startswith("out")}, before)
        self.assertEqual(sorted(k for k in after if k.startswith("out")), [os.path.join("out", "manifest.yaml")])


class TestCommandLine(ScanTestCase):
    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = scan.main([str(a) for a in args])
        return code, out.getvalue()

    def test_writes_a_manifest_and_a_report(self):
        self.put("a/valve.SLDPRT", "v")
        code, text = self.cli(self.src, "--out", self.out)
        self.assertEqual(code, 0)
        self.assertIn("Found 1 items", text)
        self.assertIn("Nothing in your CAD folders was changed", text)
        self.assertEqual(len(mf.load(self.out).items), 1)

    def test_refuses_to_overwrite_an_edited_manifest_or_write_inside_the_source(self):
        self.put("a/valve.SLDPRT", "v")
        self.assertEqual(self.cli(self.src, "--out", self.out)[0], 0)
        self.out.write_text(self.out.read_text() + "# my edits\n")
        code, text = self.cli(self.src, "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("--force", text)
        self.assertIn("# my edits", self.out.read_text())
        self.assertEqual(self.cli(self.src, "--out", self.out, "--force")[0], 0)
        code, text = self.cli(self.src, "--out", self.src / "manifest.yaml")
        self.assertEqual(code, 1)
        self.assertFalse((self.src / "manifest.yaml").exists())

    def test_a_missing_folder_is_an_error_message_not_a_crash(self):
        code, text = self.cli(self.root / "nowhere", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("Not a folder", text)


class TestManifest(ScanTestCase):
    def make(self):
        self.put("a/valve.SLDPRT", "v")
        self.put("a/valve.SLDDRW", "d")
        self.put("McMaster/bolt.SLDPRT", "b")
        self.put("b/copy.SLDPRT", "v")
        return self.run_scan()

    def test_round_trip_keeps_everything(self):
        original = self.make()
        mf.save(original, self.out)
        loaded = mf.load(self.out)
        self.assertEqual(loaded.sources, original.sources)
        self.assertEqual(loaded.stats, original.stats)
        self.assertEqual(loaded.created_at, original.created_at)
        self.assertEqual(loaded.items, original.items)
        text = self.out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Litterbox import manifest."))
        self.assertNotIn("\r", text)

    def test_long_paths_stay_on_one_line_so_they_are_easy_to_edit(self):
        long_name = "Corrosion-Resistant 18-8 Stainless Steel Hex Nuts " * 3
        self.put(f"some folder/91841A007_{long_name}.SLDPRT")
        mf.save(self.run_scan(), self.out)
        text = self.out.read_text(encoding="utf-8")
        self.assertEqual(sum(1 for line in text.splitlines() if "path:" in line), 1)
        self.assertEqual(mf.load(self.out).items[0].files[0].path, self.run_scan().items[0].files[0].path)

    def test_hand_edits_are_read(self):
        mf.save(self.make(), self.out)
        text = self.out.read_text(encoding="utf-8")
        at = text.index("name: bolt")                       # which item comes first depends on the system
        flag = text.rindex("include: true", 0, at)           # "include" is written just before "name"
        text = text[:flag] + "include: false" + text[flag + len("include: true"):]
        self.out.write_text(text.replace("name: bolt", "name: Hex bolt M6", 1), encoding="utf-8")
        loaded = {item.name: item for item in mf.load(self.out).items}
        self.assertIn("Hex bolt M6", loaded)
        self.assertFalse(loaded["Hex bolt M6"].include)
        self.assertTrue(loaded["valve"].include)

    def test_mistakes_are_reported_with_the_item_they_are_in(self):
        mf.save(self.make(), self.out)
        good = self.out.read_text(encoding="utf-8")
        cases = {
            "include: maybe": good.replace("  include: true\n", "  include: maybe\n", 1),
            "cots: 1": good.replace("  cots: false\n", "  cots: 1\n", 1),
            "kind: gizmo": good.replace("kind: part", "kind: gizmo", 1),
            "manifest_version: 2": good.replace("manifest_version: 1", "manifest_version: 2", 1),
            "items: []": good.split("items:\n")[0] + "items: nope\n",
            "duplicate id": good.replace("- id: 2\n", "- id: 1\n", 1),
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                self.out.write_text(text, encoding="utf-8")
                with self.assertRaises(mf.ManifestError) as ctx:
                    mf.load(self.out)
                self.assertTrue(str(ctx.exception))
        for label, text in (("broken yaml", "items: [unclosed\n"), ("a list", "- 1\n- 2\n"), ("empty", "")):
            with self.subTest(label=label):
                self.out.write_text(text, encoding="utf-8")
                with self.assertRaises(mf.ManifestError):
                    mf.load(self.out)
        with self.assertRaises(mf.ManifestError):
            mf.load(self.root / "missing.yaml")

    def test_items_without_files_are_refused(self):
        self.out.parent.mkdir(parents=True)
        self.out.write_text("manifest_version: 1\nitems:\n- id: 1\n  name: x\n  files: []\n", encoding="utf-8")
        with self.assertRaises(mf.ManifestError) as ctx:
            mf.load(self.out)
        self.assertIn("Item 1", str(ctx.exception))

    def test_problems_lists_what_would_stop_an_import(self):
        result = self.make()
        self.assertEqual(mf.problems(result), [])
        result.items[0].name = ""
        result.items[1].name = "x" * 101
        result.items[2].include = False
        result.items[2].name = ""                     # left out, so it doesn't matter
        found = mf.problems(result)
        self.assertEqual(len(found), 2)
        self.assertIn("has no name", found[0])

    def test_specs_cover_only_included_items_that_have_no_part_number_yet(self):
        result = self.make()
        result.items[0].include = False
        result.items[1].pn = "HCR-00009-001"
        items, specs = mf.specs(result)
        self.assertEqual([i.id for i in items], [result.items[2].id])
        self.assertTrue(all(s.imported for s in specs))
        self.assertEqual([s.import_path for s in specs], [i.main_path for i in items])
        self.assertEqual([s.description for s in specs], [i.description for i in items])
        mf.record_assignments(result, items, [PN("HCR", 20, 1)])
        self.assertEqual(items[0].pn, "HCR-00020-001")
        self.assertEqual(mf.specs(result)[0], [])                              # nothing left to do


if __name__ == "__main__":
    unittest.main()