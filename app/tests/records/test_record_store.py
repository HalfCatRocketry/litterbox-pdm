"""Tests for records/record_store.py and record_model.py: creating, loading, saving and listing records."""

import os
import stat
import unittest
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.core.part_number import PN
from litterbox.records.record_model import PNExistsError, RegistryError
from tests.support.registry_case import TIMESTAMP, RegistryTestCase


class TestCreateAndLoad(RegistryTestCase):
    def test_create_writes_a_file_and_loads_back_identically(self):
        created = self.make(42)
        self.assertTrue((self.repo / "PN-logs" / "HCR-00042-001.yaml").is_file())
        self.assertEqual(record_store.load(self.repo, PN("HCR", 42, 1)), created)

    def test_new_record_contents(self):
        record = self.make(42, name="Front upright")
        self.assertEqual(record.status, record_model.STATUS_IN_WORK)
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
        self.assertEqual(record_store.load(self.repo, PN("HCR", 42, 1)).name, "Original")

    def test_name_and_creator_are_required(self):
        with self.assertRaises(RegistryError):
            record_store.create_record(self.repo, PN("HCR", 1, 1), "   ", "Alex")
        with self.assertRaises(RegistryError):
            record_store.create_record(self.repo, PN("HCR", 1, 1), "A part", "")
        self.assertEqual(record_store.list_pns(self.repo), [])

    def test_description_is_optional_and_cots_defaults_to_false(self):
        record = self.make(3)
        self.assertEqual((record.description, record.cots, record.imported, record.import_path),
                         ("", False, False, ""))
        text = (self.repo / "PN-logs" / "HCR-00003-001.yaml").read_text(encoding="utf-8")
        self.assertIn("cots: false", text)
        self.assertIn("imported: false", text)
        self.assertNotIn("import_path", text)                # not used for created parts
        record = self.make(4, description="Left side, 6061, tag: bracket", cots=True)
        loaded = record_store.load(self.repo, record.pn)
        self.assertEqual((loaded.description, loaded.cots), ("Left side, 6061, tag: bracket", True))

    def test_imported_parts_keep_their_import_path(self):
        record = self.make(5, description="old_valve.SLDPRT", imported=True, import_path=r"D:\Old\valve\old_valve.SLDPRT")
        loaded = record_store.load(self.repo, record.pn)
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
        record = record_store.load(self.repo, PN("HCR", 9, 1))
        self.assertEqual((record.name, record.description, record.cots, record.imported),
                         ("Old style part", "", False, False))

    def test_cots_part_cannot_be_checked_out_or_released(self):
        record = self.make(7)
        record_lifecycle.mark_cots(record, "Alex", ["cad/x.SLDPRT"])
        self.assertTrue(record.cots)
        self.assertEqual((record.status, record.history[-1]["event"]), ("in_work", "made_cots"))
        with self.assertRaises(RegistryError):
            record_lifecycle.record_checkout(record, "Alex", [])
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_released(record, "Alex", [])
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_cots(record, "Alex", [])          # already COTS
        record_lifecycle.mark_void(record, "Alex", "mistake")        # but it can be voided

    def test_reopen_undoes_make_cots(self):
        record = self.make(9)
        record_lifecycle.mark_cots(record, "Alex", [])
        record_lifecycle.mark_reopened(record, "Alex", "Was modified after all")
        self.assertEqual((record.cots, record.status), (False, "in_work"))
        self.assertEqual(record.history[-1]["event"], "reopened")
        self.assertTrue(record.history[-1]["was_cots"])
        record_lifecycle.record_checkout(record, "Alex", [])          # can be checked out again
        with self.assertRaises(RegistryError):                 # a plain in-work part can't be reopened
            record_lifecycle.mark_reopened(self.make(10), "Alex", "why")

    def test_edit_details_records_what_changed(self):
        record = self.make(11, name="Bracket", description="old")
        self.assertIsNone(record_lifecycle.edit_details(record, "Alex", "  Bracket ", "old"))      # no change
        entry = record_lifecycle.edit_details(record, "Alex", "Bracket,  left", "")
        self.assertEqual((record.name, record.description), ("Bracket, left", ""))
        self.assertEqual(entry["event"], "edited")
        self.assertEqual(entry["changes"], ["name: 'Bracket' -> 'Bracket, left'", "description: 'old' -> ''"])
        with self.assertRaises(RegistryError):
            record_lifecycle.edit_details(record, "Alex", "   ", "x")

    def test_revision_fields_round_trip_and_events_say_which_revision(self):
        record = self.make(20)
        self.assertEqual((record.revision, record.released_revision), ("A", ""))
        self.assertEqual(record.history[0]["revision"], "A")
        record_lifecycle.mark_released(record, "Jo", ["cad/HCR-00020-001_A.SLDPRT"])
        self.assertEqual((record.revision, record.released_revision, record.history[-1]["revision"]), ("A", "A", "A"))
        record.revision = "B"
        record.status = "in_work"
        path = self.repo / "PN-logs" / "HCR-00020-001.yaml"
        path.chmod(0o644)
        record_store.save(self.repo, record)
        loaded = record_store.load(self.repo, record.pn)
        self.assertEqual((loaded.revision, loaded.released_revision, loaded.status), ("B", "A", "in_work"))

    def test_reopening_goes_back_to_the_earlier_released_revision(self):
        record = self.make(21)
        record_lifecycle.mark_released(record, "Jo", [])                  # A released
        record.revision, record.status = "B", "in_work"            # (what Revise will do)
        record_lifecycle.mark_released(record, "Jo", [])                  # B released
        self.assertEqual(record.released_revision, "B")
        record_lifecycle.mark_reopened(record, "Jo", "Released too early")
        self.assertEqual((record.revision, record.released_revision, record.status), ("B", "A", "in_work"))
        first = self.make(22)
        record_lifecycle.mark_released(first, "Jo", [])
        record_lifecycle.mark_reopened(first, "Jo", "Oops")
        self.assertEqual(first.released_revision, "")

    def test_bad_revision_fields_are_refused(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        for number, extra in enumerate(("revision: 7\n", "revision: A\nreleased_revision: C\n"), start=30):
            (folder / f"HCR-000{number}-001.yaml").write_text(
                f"org: HCR\npn: '000{number}-001'\n{extra}name: X\nstatus: in_work\n", encoding="utf-8")
            with self.assertRaises(RegistryError):
                record_store.load(self.repo, PN("HCR", number, 1))

    def test_the_pn_inside_must_match_the_file_name(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00040-001.yaml").write_text(
            "org: HCR\npn: '00041-001'\nname: X\nstatus: in_work\n", encoding="utf-8")
        with self.assertRaises(RegistryError) as ctx:
            record_store.load(self.repo, PN("HCR", 40, 1))
        self.assertIn("named", str(ctx.exception))

    def test_a_record_with_a_full_pn_and_no_revision_still_reads(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00050-001.yaml").write_text(
            "pn: HCR-00050-001\nname: Old style\nstatus: in_work\n", encoding="utf-8")
        record = record_store.load(self.repo, PN("HCR", 50, 1))
        self.assertEqual((record.pn, record.revision, record.released_revision), (PN("HCR", 50, 1), "A", ""))

    def test_only_in_work_parts_can_be_made_cots(self):
        record = self.make(8)
        record_lifecycle.mark_void(record, "Alex", "gone")
        with self.assertRaises(RegistryError):
            record_lifecycle.mark_cots(record, "Alex", [])

    def test_cots_must_be_true_or_false(self):
        folder = self.repo / "PN-logs"
        folder.mkdir()
        (folder / "HCR-00009-001.yaml").write_text(
            "pn: HCR-00009-001\nname: X\ncots: maybe\nstatus: in_work\n", encoding="utf-8")
        with self.assertRaises(RegistryError):
            record_store.load(self.repo, PN("HCR", 9, 1))

    def test_load_missing_record(self):
        with self.assertRaises(RegistryError):
            record_store.load(self.repo, PN("HCR", 99, 1))

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
        self.assertEqual(record_store.load(self.repo, PN("HCR", 1, 1)).name,
                         "Ø10 locating pin – steel")

    def test_numeric_looking_name_stays_text(self):
        self.make(1, name="12345")
        self.assertEqual(record_store.load(self.repo, PN("HCR", 1, 1)).name, "12345")

    def test_unquoted_timestamp_in_hand_edited_file_is_read_as_text(self):
        path = self.repo / "PN-logs"
        path.mkdir()
        (path / "HCR-00007-001.yaml").write_text(
            "pn: HCR-00007-001\ndescription: Hand made\nstatus: in_work\n"
            "created_by: Jo\ncreated_at: 2026-10-04T21:32:10Z\n"
            "history:\n- {event: created, by: Jo, at: 2026-10-04T21:32:10Z}\n",
            encoding="utf-8",
        )
        record = record_store.load(self.repo, PN("HCR", 7, 1))
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
                    record_store.load(self.repo, PN("HCR", base, 1))


class TestSave(RegistryTestCase):
    def test_changes_are_saved(self):
        record = self.make(42)
        record_lifecycle.record_checkout(record, "Alex Smith", ["cad/HCR-00042-001_A.SLDPRT"])
        record_store.save(self.repo, record)
        loaded = record_store.load(self.repo, record.pn)
        self.assertEqual(len(loaded.history), 2)
        self.assertEqual(loaded.history[1]["files"], ["cad/HCR-00042-001_A.SLDPRT"])
        self.assertEqual(loaded, record)

    def test_no_temp_files_left_behind(self):
        record = self.make(42)
        record_store.save(self.repo, record)
        self.assertEqual([p.name for p in (self.repo / "PN-logs").iterdir()], ["HCR-00042-001.yaml"])

    def test_unknown_fields_survive_a_round_trip(self):
        record = self.make(42)
        path = record_store.record_path(self.repo, record.pn)
        path.write_text(path.read_text(encoding="utf-8") + "future_field: {a: 1}\n", encoding="utf-8")
        loaded = record_store.load(self.repo, record.pn)
        record_lifecycle.add_event(loaded, "checked_in", "Alex Smith", files=["x"])
        record_store.save(self.repo, loaded)
        self.assertEqual(record_store.load(self.repo, record.pn).extra, {"future_field": {"a": 1}})

    def test_saving_a_record_that_does_not_exist_is_refused(self):
        record = self.make(42)
        record_store.record_path(self.repo, record.pn).unlink()
        with self.assertRaises(RegistryError):
            record_store.save(self.repo, record)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores read-only flags")
    def test_read_only_record_is_refused(self):
        record = self.make(42)
        path = record_store.record_path(self.repo, record.pn)
        path.chmod(stat.S_IREAD)
        self.addCleanup(lambda: path.chmod(stat.S_IWRITE | stat.S_IREAD))
        with self.assertRaises(RegistryError) as ctx:
            record_store.save(self.repo, record)
        self.assertIn("read-only", str(ctx.exception))


class TestListing(RegistryTestCase):
    def test_empty_vault(self):
        self.assertEqual(record_store.list_pns(self.repo), [])
        self.assertEqual(record_store.next_free_base(self.repo), 1)
        self.assertEqual(record_store.next_free_variant(self.repo, 5), 1)

    def test_lists_and_sets(self):
        self.make(1)
        self.make(1, 2)
        self.make(5)
        self.assertEqual([str(p) for p in record_store.list_pns(self.repo)],
                         ["HCR-00001-001", "HCR-00001-002", "HCR-00005-001"])
        self.assertEqual(record_store.used_bases(self.repo), {1, 5})
        self.assertEqual(record_store.used_variants(self.repo, 1), {1, 2})
        self.assertEqual(record_store.used_variants(self.repo, 9), set())

    def test_non_record_files_are_ignored(self):
        self.make(1)
        folder = self.repo / "PN-logs"
        for name in ("README.txt", "notes.yaml", ".tmp-abc.yaml", "HCR-1-1.yaml", "HCR-00000-001.yaml"):
            (folder / name).write_text("x", encoding="utf-8")
        (folder / "subfolder").mkdir()
        self.assertEqual(record_store.used_bases(self.repo), {1})

    def test_lowest_unused_fills_gaps(self):
        self.make(1)
        self.make(3)                               # typed in by hand, skipping 2
        self.assertEqual(record_store.next_free_base(self.repo), 2)
        self.make(2)
        self.assertEqual(record_store.next_free_base(self.repo), 4)

    def test_manual_number_is_skipped_when_sequence_reaches_it(self):
        self.make(3)
        taken = []
        for _ in range(4):
            base = record_store.next_free_base(self.repo)
            self.make(base)
            taken.append(base)
        self.assertEqual(taken, [1, 2, 4, 5])

    def test_variants_fill_gaps_per_base(self):
        self.make(10, 1)
        self.make(10, 4)                           # typed in by hand
        self.make(11, 1)
        self.assertEqual(record_store.next_free_variant(self.repo, 10), 2)
        self.assertEqual(record_store.next_free_variant(self.repo, 11), 2)

    def test_void_numbers_stay_used_forever(self):
        record = self.make(1)
        record_lifecycle.mark_void(record, "Alex Smith", "never built")
        record_store.save(self.repo, record)
        self.assertEqual(record_store.next_free_base(self.repo), 2)
        self.assertIn(1, record_store.used_bases(self.repo))

    def test_load_variants_for_the_dialog(self):
        self.make(10, 1, name="Left")
        self.make(10, 2, name="Right")
        self.make(11, 1, name="Other")
        rows = record_store.load_variants(self.repo, 10)
        self.assertEqual([(str(r.pn), r.name) for r in rows],
                         [("HCR-00010-001", "Left"), ("HCR-00010-002", "Right")])

    def test_org_filter(self):
        self.make(1, org="HCR")
        self.make(1, org="FSAE")
        self.assertEqual(record_store.used_bases(self.repo, org="HCR"), {1})
        self.assertEqual(len(record_store.list_pns(self.repo)), 2)


if __name__ == "__main__":
    unittest.main()
