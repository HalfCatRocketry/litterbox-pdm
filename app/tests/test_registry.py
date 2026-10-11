"""Tests for registry.py. Run from the app folder with:  python -m unittest discover -s tests -v"""

import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

import registry
from pn import PN
from registry import PNExistsError, RegistryError

TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)

    def make(self, base, variant=1, name="Test part", org="HCR", **fields):
        return registry.create_record(self.repo, PN(org, base, variant), name, "Alex Smith", **fields)


class TestCreateAndLoad(RegistryTestCase):
    def test_create_writes_a_file_and_loads_back_identically(self):
        created = self.make(42)
        self.assertTrue((self.repo / "PN-logs" / "HCR-00042-001.yaml").is_file())
        self.assertEqual(registry.load(self.repo, PN("HCR", 42, 1)), created)

    def test_new_record_contents(self):
        record = self.make(42, name="Front upright")
        self.assertEqual(record.status, registry.STATUS_IN_WORK)
        self.assertEqual(record.name, "Front upright")
        self.assertEqual(record.created_by, "Alex Smith")
        self.assertRegex(record.created_at, TIMESTAMP)
        self.assertEqual(len(record.history), 1)
        self.assertEqual(record.history[0]["event"], "created")
        self.assertEqual(record.history[0]["at"], record.created_at)

    def test_duplicate_is_refused_and_original_untouched(self):
        self.make(42, name="Original")
        with self.assertRaises(PNExistsError):
            self.make(42, name="Imposter")
        self.assertEqual(registry.load(self.repo, PN("HCR", 42, 1)).name, "Original")

    def test_name_and_creator_are_required(self):
        with self.assertRaises(RegistryError):
            registry.create_record(self.repo, PN("HCR", 1, 1), "   ", "Alex")
        with self.assertRaises(RegistryError):
            registry.create_record(self.repo, PN("HCR", 1, 1), "A part", "")
        self.assertEqual(registry.list_pns(self.repo), [])

    def test_description_is_optional_and_cots_defaults_to_false(self):
        record = self.make(3)
        self.assertEqual((record.description, record.cots, record.imported, record.import_path),
                         ("", False, False, ""))
        text = (self.repo / "PN-logs" / "HCR-00003-001.yaml").read_text(encoding="utf-8")
        self.assertIn("cots: false", text)
        self.assertIn("imported: false", text)
        self.assertNotIn("import_path", text)                # not used for created parts
        record = self.make(4, description="Left side, 6061, tag: bracket", cots=True)
        loaded = registry.load(self.repo, record.pn)
        self.assertEqual((loaded.description, loaded.cots), ("Left side, 6061, tag: bracket", True))

    def test_imported_parts_keep_their_import_path(self):
        record = self.make(5, description="old_valve.SLDPRT", imported=True, import_path=r"D:\Old\valve\old_valve.SLDPRT")
        loaded = registry.load(self.repo, record.pn)
        self.assertTrue(loaded.imported)
        self.assertEqual(loaded.import_path, r"D:\Old\valve\old_valve.SLDPRT")
        self.assertEqual(loaded.description, "old_valve.SLDPRT")
        created = self.make(6, import_path="ignored")        # import_path only counts for imported parts
        self.assertEqual(created.import_path, "")

    def test_records_from_before_names_existed_still_load(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00009-001.yaml").write_text(
            "pn: HCR-00009-001\norg: HCR\nbase: 9\nvariant: 1\ndescription: Old style part\n"
            "status: in_work\ncreated_by: Alex\ncreated_at: '2026-01-01T00:00:00Z'\n", encoding="utf-8")
        record = registry.load(self.repo, PN("HCR", 9, 1))
        self.assertEqual((record.name, record.description, record.cots, record.imported),
                         ("Old style part", "", False, False))

    def test_cots_part_cannot_be_checked_out_or_released(self):
        record = self.make(7)
        registry.mark_cots(record, "Alex", ["cad/x.SLDPRT"])
        self.assertTrue(record.cots)
        self.assertEqual((record.status, record.history[-1]["event"]), ("in_work", "made_cots"))
        with self.assertRaises(RegistryError):
            registry.record_checkout(record, "Alex", [])
        with self.assertRaises(RegistryError):
            registry.mark_released(record, "Alex", [])
        with self.assertRaises(RegistryError):
            registry.mark_cots(record, "Alex", [])          # already COTS
        registry.mark_void(record, "Alex", "mistake")        # but it can be voided

    def test_reopen_undoes_make_cots(self):
        record = self.make(9)
        registry.mark_cots(record, "Alex", [])
        registry.mark_reopened(record, "Alex", "Was modified after all")
        self.assertEqual((record.cots, record.status), (False, "in_work"))
        self.assertEqual(record.history[-1]["event"], "reopened")
        self.assertTrue(record.history[-1]["was_cots"])
        registry.record_checkout(record, "Alex", [])          # can be checked out again
        with self.assertRaises(RegistryError):                 # a plain in-work part can't be reopened
            registry.mark_reopened(self.make(10), "Alex", "why")

    def test_edit_details_records_what_changed(self):
        record = self.make(11, name="Bracket", description="old")
        self.assertIsNone(registry.edit_details(record, "Alex", "  Bracket ", "old"))      # no change
        entry = registry.edit_details(record, "Alex", "Bracket,  left", "")
        self.assertEqual((record.name, record.description), ("Bracket, left", ""))
        self.assertEqual(entry["event"], "edited")
        self.assertEqual(entry["changes"], ["name: 'Bracket' -> 'Bracket, left'", "description: 'old' -> ''"])
        with self.assertRaises(RegistryError):
            registry.edit_details(record, "Alex", "   ", "x")

    def test_revision_fields_round_trip_and_events_say_which_revision(self):
        record = self.make(20)
        self.assertEqual((record.revision, record.released_revision), ("A", ""))
        self.assertEqual(record.history[0]["revision"], "A")
        registry.mark_released(record, "Jo", ["cad/HCR-00020-001_A.SLDPRT"])
        self.assertEqual((record.revision, record.released_revision, record.history[-1]["revision"]), ("A", "A", "A"))
        record.revision = "B"
        record.status = "in_work"
        path = self.repo / "PN-logs" / "HCR-00020-001.yaml"
        path.chmod(0o644)
        registry.save(self.repo, record)
        loaded = registry.load(self.repo, record.pn)
        self.assertEqual((loaded.revision, loaded.released_revision, loaded.status), ("B", "A", "in_work"))

    def test_reopening_goes_back_to_the_earlier_released_revision(self):
        record = self.make(21)
        registry.mark_released(record, "Jo", [])                  # A released
        record.revision, record.status = "B", "in_work"            # (what Revise will do)
        registry.mark_released(record, "Jo", [])                  # B released
        self.assertEqual(record.released_revision, "B")
        registry.mark_reopened(record, "Jo", "Released too early")
        self.assertEqual((record.revision, record.released_revision, record.status), ("B", "A", "in_work"))
        first = self.make(22)
        registry.mark_released(first, "Jo", [])
        registry.mark_reopened(first, "Jo", "Oops")
        self.assertEqual(first.released_revision, "")

    def test_bad_revision_fields_are_refused(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        for number, extra in enumerate(("revision: 7\n", "revision: A\nreleased_revision: C\n"), start=30):
            (folder / f"HCR-000{number}-001.yaml").write_text(
                f"org: HCR\npn: '000{number}-001'\n{extra}name: X\nstatus: in_work\n", encoding="utf-8")
            with self.assertRaises(RegistryError):
                registry.load(self.repo, PN("HCR", number, 1))

    def test_the_pn_inside_must_match_the_file_name(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00040-001.yaml").write_text(
            "org: HCR\npn: '00041-001'\nname: X\nstatus: in_work\n", encoding="utf-8")
        with self.assertRaises(RegistryError) as ctx:
            registry.load(self.repo, PN("HCR", 40, 1))
        self.assertIn("named", str(ctx.exception))

    def test_a_record_with_a_full_pn_and_no_revision_still_reads(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00050-001.yaml").write_text(
            "pn: HCR-00050-001\nname: Old style\nstatus: in_work\n", encoding="utf-8")
        record = registry.load(self.repo, PN("HCR", 50, 1))
        self.assertEqual((record.pn, record.revision, record.released_revision), (PN("HCR", 50, 1), "A", ""))

    def test_only_in_work_parts_can_be_made_cots(self):
        record = self.make(8)
        registry.mark_void(record, "Alex", "gone")
        with self.assertRaises(RegistryError):
            registry.mark_cots(record, "Alex", [])

    def test_cots_must_be_true_or_false(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00009-001.yaml").write_text(
            "pn: HCR-00009-001\nname: X\ncots: maybe\nstatus: in_work\n", encoding="utf-8")
        with self.assertRaises(RegistryError):
            registry.load(self.repo, PN("HCR", 9, 1))

    def test_load_missing_record(self):
        with self.assertRaises(RegistryError):
            registry.load(self.repo, PN("HCR", 99, 1))

    def test_yaml_file_format(self):
        self.make(42)
        text = (self.repo / "PN-logs" / "HCR-00042-001.yaml").read_text(encoding="utf-8")
        self.assertIn("org: HCR\n", text)
        self.assertIn("pn: '00042-001'", text)               # always quoted, without the org
        self.assertIn("revision: A", text)
        self.assertNotIn("base:", text)
        self.assertRegex(text, r"created_at: '?\d{4}-")      # quoted timestamp
        self.assertNotIn("\r", text)                         # LF line endings

    def test_unicode_name(self):
        self.make(1, name="Ø10 locating pin – steel")
        self.assertEqual(registry.load(self.repo, PN("HCR", 1, 1)).name,
                         "Ø10 locating pin – steel")

    def test_numeric_looking_name_stays_text(self):
        self.make(1, name="12345")
        self.assertEqual(registry.load(self.repo, PN("HCR", 1, 1)).name, "12345")

    def test_unquoted_timestamp_in_hand_edited_file_is_read_as_text(self):
        path = self.repo / "PN-logs"
        path.mkdir()
        (path / "HCR-00007-001.yaml").write_text(
            "pn: HCR-00007-001\ndescription: Hand made\nstatus: in_work\n"
            "created_by: Jo\ncreated_at: 2026-10-04T21:32:10Z\n"
            "history:\n- {event: created, by: Jo, at: 2026-10-04T21:32:10Z}\n",
            encoding="utf-8",
        )
        record = registry.load(self.repo, PN("HCR", 7, 1))
        self.assertEqual(record.created_at, "2026-10-04T21:32:10Z")
        self.assertEqual(record.history[0]["at"], "2026-10-04T21:32:10Z")

    def test_bad_files_raise_clear_errors(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00001-001.yaml").write_text("", encoding="utf-8")
        (folder / "HCR-00002-001.yaml").write_text("pn: HCR-00002-001\nstatus: banana\n", encoding="utf-8")
        (folder / "HCR-00003-001.yaml").write_text("pn: HCR-00099-001\n", encoding="utf-8")
        (folder / "HCR-00004-001.yaml").write_text("just: [broken\n", encoding="utf-8")
        for base in (1, 2, 3, 4):
            with self.subTest(base=base):
                with self.assertRaises(RegistryError):
                    registry.load(self.repo, PN("HCR", base, 1))


class TestSave(RegistryTestCase):
    def test_changes_are_saved(self):
        record = self.make(42)
        registry.record_checkout(record, "Alex Smith", ["cad/HCR-00042-001_A.SLDPRT"])
        registry.save(self.repo, record)
        loaded = registry.load(self.repo, record.pn)
        self.assertEqual(len(loaded.history), 2)
        self.assertEqual(loaded.history[1]["files"], ["cad/HCR-00042-001_A.SLDPRT"])
        self.assertEqual(loaded, record)

    def test_no_temp_files_left_behind(self):
        record = self.make(42)
        registry.save(self.repo, record)
        self.assertEqual([p.name for p in (self.repo / "PN-logs").iterdir()], ["HCR-00042-001.yaml"])

    def test_unknown_fields_survive_a_round_trip(self):
        record = self.make(42)
        path = registry.record_path(self.repo, record.pn)
        path.write_text(path.read_text(encoding="utf-8") + "future_field: {a: 1}\n", encoding="utf-8")
        loaded = registry.load(self.repo, record.pn)
        registry.add_event(loaded, "checked_in", "Alex Smith", files=["x"])
        registry.save(self.repo, loaded)
        self.assertEqual(registry.load(self.repo, record.pn).extra, {"future_field": {"a": 1}})

    def test_saving_a_record_that_does_not_exist_is_refused(self):
        record = self.make(42)
        registry.record_path(self.repo, record.pn).unlink()
        with self.assertRaises(RegistryError):
            registry.save(self.repo, record)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores read-only flags")
    def test_read_only_record_is_refused(self):
        record = self.make(42)
        path = registry.record_path(self.repo, record.pn)
        path.chmod(stat.S_IREAD)
        self.addCleanup(lambda: path.chmod(stat.S_IWRITE | stat.S_IREAD))
        with self.assertRaises(RegistryError) as ctx:
            registry.save(self.repo, record)
        self.assertIn("read-only", str(ctx.exception))


class TestListing(RegistryTestCase):
    def test_empty_vault(self):
        self.assertEqual(registry.list_pns(self.repo), [])
        self.assertEqual(registry.next_free_base(self.repo), 1)
        self.assertEqual(registry.next_free_variant(self.repo, 5), 1)

    def test_lists_and_sets(self):
        self.make(1)
        self.make(1, 2)
        self.make(5)
        self.assertEqual([str(p) for p in registry.list_pns(self.repo)],
                         ["HCR-00001-001", "HCR-00001-002", "HCR-00005-001"])
        self.assertEqual(registry.used_bases(self.repo), {1, 5})
        self.assertEqual(registry.used_variants(self.repo, 1), {1, 2})
        self.assertEqual(registry.used_variants(self.repo, 9), set())

    def test_non_record_files_are_ignored(self):
        self.make(1)
        folder = self.repo / "PN-logs"
        for name in ("README.txt", "notes.yaml", ".tmp-abc.yaml", "HCR-1-1.yaml", "HCR-00000-001.yaml"):
            (folder / name).write_text("x", encoding="utf-8")
        (folder / "subfolder").mkdir()
        self.assertEqual(registry.used_bases(self.repo), {1})

    def test_lowest_unused_fills_gaps(self):
        self.make(1)
        self.make(3)                               # typed in by hand, skipping 2
        self.assertEqual(registry.next_free_base(self.repo), 2)
        self.make(2)
        self.assertEqual(registry.next_free_base(self.repo), 4)

    def test_manual_number_is_skipped_when_sequence_reaches_it(self):
        self.make(3)
        taken = []
        for _ in range(4):
            base = registry.next_free_base(self.repo)
            self.make(base)
            taken.append(base)
        self.assertEqual(taken, [1, 2, 4, 5])

    def test_variants_fill_gaps_per_base(self):
        self.make(10, 1)
        self.make(10, 4)                           # typed in by hand
        self.make(11, 1)
        self.assertEqual(registry.next_free_variant(self.repo, 10), 2)
        self.assertEqual(registry.next_free_variant(self.repo, 11), 2)

    def test_void_numbers_stay_used_forever(self):
        record = self.make(1)
        registry.mark_void(record, "Alex Smith", "never built")
        registry.save(self.repo, record)
        self.assertEqual(registry.next_free_base(self.repo), 2)
        self.assertIn(1, registry.used_bases(self.repo))

    def test_load_variants_for_the_dialog(self):
        self.make(10, 1, name="Left")
        self.make(10, 2, name="Right")
        self.make(11, 1, name="Other")
        rows = registry.load_variants(self.repo, 10)
        self.assertEqual([(str(r.pn), r.name) for r in rows],
                         [("HCR-00010-001", "Left"), ("HCR-00010-002", "Right")])

    def test_org_filter(self):
        self.make(1, org="HCR")
        self.make(1, org="FSAE")
        self.assertEqual(registry.used_bases(self.repo, org="HCR"), {1})
        self.assertEqual(len(registry.list_pns(self.repo)), 2)


class TestCadFiles(RegistryTestCase):
    def test_finds_only_files_for_that_pn(self):
        cad = self.repo / "cad"
        cad.mkdir()
        for name in ("HCR-00042-001_A.SLDPRT", "HCR-00042-001_A.SLDDRW", "HCR-00042-002_A.SLDPRT",
                     "~$HCR-00042-001_A.SLDPRT", "notes.txt", "hcr-00043-001.sldprt"):
            (cad / name).write_bytes(b"x")
        (cad / "HCR-00042-001.folder").mkdir()
        self.assertEqual(registry.cad_files(self.repo, PN("HCR", 42, 1), "A"),
                         ["cad/HCR-00042-001_A.SLDDRW", "cad/HCR-00042-001_A.SLDPRT"])
        self.assertEqual(registry.cad_files(self.repo, PN("HCR", 43, 1), "A"), [])   # no revision on the name: not ours
        self.assertEqual(registry.cad_files(self.repo, PN("HCR", 99, 1), "A"), [])
        self.assertEqual(registry.cad_files(self.repo, PN("HCR", 42, 1), "B"), [])

    def test_cad_index_groups_every_pn_in_one_scan(self):
        cad = self.repo / "cad"
        cad.mkdir()
        for name in ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW", "HCR-00002-001_A.SLDPRT", "junk.txt"):
            (cad / name).write_bytes(b"x")
        index = registry.cad_index(self.repo)
        self.assertEqual(index, {
            PN("HCR", 1, 1): {"A": ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]},
            PN("HCR", 2, 1): {"A": ["cad/HCR-00002-001_A.SLDPRT"]},
        })
        self.assertEqual(registry.cad_index(self.repo / "nowhere"), {})

    def test_every_revision_is_indexed_and_the_working_one_is_the_default(self):
        cad = self.repo / "cad"
        cad.mkdir()
        record = self.make(5)
        for name in ("HCR-00005-001_A.SLDPRT", "HCR-00005-001_B.SLDPRT", "HCR-00005-001_B.SLDDRW"):
            (cad / name).write_bytes(b"x")
        self.assertEqual(sorted(registry.cad_index(self.repo)[record.pn]), ["A", "B"])
        self.assertEqual(registry.cad_files(self.repo, record.pn), ["cad/HCR-00005-001_A.SLDPRT"])   # working is A
        record.revision = "B"
        path = self.repo / "PN-logs" / "HCR-00005-001.yaml"
        path.chmod(0o644)
        registry.save(self.repo, record)
        self.assertEqual(len(registry.cad_files(self.repo, record.pn)), 2)
        self.assertEqual(len(registry.all_cad_files(self.repo, record.pn)), 3)

    def test_missing_cad_folder(self):
        self.assertEqual(registry.cad_files(self.repo, PN("HCR", 1, 1), "A"), [])


class TestStatusChanges(RegistryTestCase):
    FILES = ["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW"]

    def test_full_lifecycle(self):
        record = self.make(1)
        registry.record_checkout(record, "Alex", self.FILES)
        registry.record_checkin(record, "Alex", self.FILES, "Added fillet")
        registry.mark_released(record, "Jo", self.FILES)
        self.assertEqual(record.status, "released")
        registry.mark_reopened(record, "Jo", "Bore diameter wrong")
        self.assertEqual(record.status, "in_work")
        self.assertEqual([e["event"] for e in record.history],
                         ["created", "checked_out", "checked_in", "released", "reopened"])
        registry.save(self.repo, record)
        self.assertEqual(registry.load(self.repo, record.pn), record)
        for event in record.history:
            self.assertRegex(event["at"], TIMESTAMP)

    def test_event_details(self):
        record = self.make(1)
        registry.record_checkin(record, "Alex", self.FILES, "  Added fillet ")
        self.assertEqual(record.history[-1]["comment"], "Added fillet")
        registry.record_checkin(record, "Alex", self.FILES)
        self.assertNotIn("comment", record.history[-1])

    def test_released_part_cannot_be_checked_out(self):
        record = self.make(1)
        registry.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            registry.record_checkout(record, "Alex", self.FILES)

    def test_cannot_release_twice_or_reopen_unreleased(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            registry.mark_reopened(record, "Jo", "reason")
        registry.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            registry.mark_released(record, "Jo", self.FILES)

    def test_reopen_and_void_need_a_reason(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            registry.mark_void(record, "Jo", "  ")
        self.assertEqual(record.status, "in_work")
        registry.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):
            registry.mark_reopened(record, "Jo", "")
        self.assertEqual(record.status, "released")

    def test_void_rules(self):
        record = self.make(1)
        registry.mark_released(record, "Jo", self.FILES)
        with self.assertRaises(RegistryError):          # must reopen first
            registry.mark_void(record, "Jo", "scrapped")
        registry.mark_reopened(record, "Jo", "changed my mind")
        registry.mark_void(record, "Jo", "scrapped")
        self.assertEqual(record.status, "void")
        with self.assertRaises(RegistryError):
            registry.mark_reopened(record, "Jo", "oops")

    def test_events_need_a_user(self):
        record = self.make(1)
        with self.assertRaises(RegistryError):
            registry.add_event(record, "checked_in", "  ")


if __name__ == "__main__":
    unittest.main()