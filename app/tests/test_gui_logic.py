"""Tests for gui_logic.py and settings.py (no windows involved)."""

import tempfile
import unittest
from pathlib import Path

import gui_logic as logic
import registry
import settings
from litterbox_engine import ChangeReport, LitterboxError, PartStatus
from pn import PN


def row(base, state="Available", kind="ok", description="", files=(), name="", import_path=""):
    return PartStatus(PN("HCR", base, 1), name or description, "in_work", state, kind, files=list(files),
                      description=description if name else "", import_path=import_path)


ROWS = [
    row(1, "Available", "ok", "Front upright"),
    row(2, "Checked out by you", "mine", "Rear upright"),
    row(3, "Checked out by Alex", "theirs", "Brake bracket"),
    row(4, "Released", "released", "Pedal"),
    row(5, "Void", "void", "Scrapped idea"),
    row(6, "Modified but not checked out", "stray", "Mystery"),
]
BY_PN = {r.pn: r for r in ROWS}


class TestFilterRows(unittest.TestCase):
    def bases(self, **kw):
        return [r.pn.base for r in logic.filter_rows(ROWS, **kw)]

    def test_default_hides_void(self):
        self.assertEqual(self.bases(), [1, 2, 3, 4, 6])

    def test_show_void(self):
        self.assertEqual(self.bases(show_void=True), [1, 2, 3, 4, 5, 6])

    def test_views(self):
        self.assertEqual(self.bases(view="Mine"), [2])
        self.assertEqual(self.bases(view="Checked out"), [2, 3])
        self.assertEqual(self.bases(view="Released"), [4])
        self.assertEqual(self.bases(view="All"), [1, 2, 3, 4, 6])

    def test_search_matches_number_or_description_ignoring_case(self):
        self.assertEqual(self.bases(search="UPRIGHT"), [1, 2])
        self.assertEqual(self.bases(search="00003"), [3])
        self.assertEqual(self.bases(search="hcr-00004-001"), [4])
        self.assertEqual(self.bases(search="  pedal "), [4])
        self.assertEqual(self.bases(search="nothing like this"), [])

    def test_filters_combine(self):
        self.assertEqual(self.bases(search="upright", view="Mine"), [2])

    def test_void_hidden_even_when_searched_unless_shown(self):
        self.assertEqual(self.bases(search="scrapped"), [])
        self.assertEqual(self.bases(search="scrapped", show_void=True), [5])


class TestFileTypes(unittest.TestCase):
    def test_solidworks_extensions_are_shortened(self):
        self.assertEqual(logic.file_types(["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]), "DRW, PRT")

    def test_other_extensions_and_duplicates(self):
        self.assertEqual(logic.file_types(["cad/a.STEP", "cad/b.STEP", "cad/c.SLDASM"]), "STEP, ASM")

    def test_empty(self):
        self.assertEqual(logic.file_types([]), "")


class TestPlanAction(unittest.TestCase):
    def plan(self, action, *bases):
        return logic.plan_action(action, [PN("HCR", b, 1) for b in bases], BY_PN)

    def test_nothing_selected(self):
        self.assertEqual(self.plan("checkout").message, "Select a part first (use its box on the left).")

    def test_checkout_uses_only_available_parts(self):
        plan = self.plan("checkout", 1, 2, 3)
        self.assertEqual([p.base for p in plan.targets], [1])
        self.assertEqual([(p.base, why) for p, why in plan.skipped],
                         [(2, "Checked out by you"), (3, "Checked out by Alex")])
        self.assertEqual(plan.message, "")

    def test_checkin_undo_save_need_your_own_checkout(self):
        for action in ("checkin", "save", "undo"):
            with self.subTest(action=action):
                self.assertEqual([p.base for p in self.plan(action, 1, 2, 3).targets], [2])

    def test_message_when_nothing_qualifies(self):
        plan = self.plan("checkout", 3)
        self.assertEqual(plan.targets, [])
        self.assertEqual(plan.message, "Can't check out HCR-00003-001: Checked out by Alex.")
        self.assertIn("None of the selected", self.plan("checkout", 3, 4).message)

    def test_single_part_actions_refuse_multiple_selection(self):
        for action in ("edit", "revise", "open"):
            with self.subTest(action=action):
                self.assertIn("just one", self.plan(action, 1, 6).message)

    def test_release_reopen_void_eligibility(self):
        self.assertEqual([p.base for p in self.plan("release", 1).targets], [1])
        self.assertIn("Can't release", self.plan("release", 4).message)      # already released
        self.assertIn("Can't release", self.plan("release", 2).message)      # checked out
        self.assertEqual([p.base for p in self.plan("reopen", 4).targets], [4])
        self.assertIn("Can't unrelease", self.plan("reopen", 1).message)
        self.assertEqual([p.base for p in self.plan("void", 1).targets], [1])
        self.assertIn("Can't void", self.plan("void", 4).message)

    def test_make_cots_and_cots_rows(self):
        cots = row(7, "COTS part", "cots", "Bolt")
        by_pn = {**BY_PN, cots.pn: cots}
        self.assertEqual([p.base for p in logic.plan_action("make_cots", [ROWS[0].pn], by_pn).targets], [1])
        for base in (2, 3, 4):                                   # checked out / released
            self.assertIn("Can't make COTS", logic.plan_action("make_cots", [PN("HCR", base, 1)], by_pn).message)
        self.assertIn("Can't make COTS", logic.plan_action("make_cots", [cots.pn], by_pn).message)
        self.assertIn("COTS part", logic.plan_action("checkout", [cots.pn], by_pn).message)
        self.assertIn("Can't release", logic.plan_action("release", [cots.pn], by_pn).message)
        self.assertEqual(logic.plan_action("reopen", [cots.pn], by_pn).targets, [cots.pn])
        self.assertIn("checked out", logic.reopen_cots_warning("HCR-00007-001"))
        self.assertEqual(logic.plan_action("void", [cots.pn], by_pn).targets, [cots.pn])

    def test_edit_details_needs_one_part_you_have_checked_out(self):
        self.assertEqual([p.base for p in self.plan("edit", 2).targets], [2])
        self.assertIn("Can't edit the details of", self.plan("edit", 1).message)       # not checked out
        self.assertIn("Can't edit the details of", self.plan("edit", 3).message)       # someone else's
        self.assertIn("just one", self.plan("edit", 2, 6).message)

    def test_edit_details_result(self):
        self.assertEqual(logic.edit_details_result("A", "d", "  ", "d"), ("A name is required.", False))
        self.assertEqual(logic.edit_details_result("A", "d", "A ", " d"), ("", False))
        self.assertEqual(logic.edit_details_result("A", "d", "B", "d"), ("", True))
        self.assertEqual(logic.edit_details_result("A", "", "A", "x"), ("", True))

    def test_history_shows_edit_changes(self):
        event = {"event": "edited", "by": "Alex", "at": "2026-10-05T14:02:41Z", "changes": ["name: 'A' -> 'B'"]}
        fake = type("R", (), {"history": [event]})()
        _when, _who, what, details = logic.format_history(fake)[0]
        self.assertEqual((what, details), ("Edited details", "name: 'A' -> 'B'"))

    def test_open_is_for_one_downloaded_part(self):
        self.assertEqual([p.base for p in self.plan("open", 1).targets], [1])
        for base in (2, 3, 4, 5, 6):                   # mine, theirs, released, void, stray
            self.assertEqual(len(self.plan("open", base).targets), 1, base)
        self.assertIn("just one", self.plan("open", 1, 2).message)
        missing = row(8, "Not downloaded", "missing", "Gone")
        message = logic.plan_action("open", [missing.pn], {missing.pn: missing}).message
        self.assertIn("Can't open", message)
        self.assertIn("no CAD files", logic.open_message(row(9, files=[])))
        self.assertEqual(logic.open_message(row(9, files=["cad/x.SLDPRT"])), "")
        self.assertIn("no drawing", logic.open_message(row(9, files=["cad/x.SLDPRT"]), drawing=True))
        self.assertEqual(logic.open_message(row(9, files=["cad/x.SLDPRT", "cad/x.SLDDRW"]), drawing=True), "")
        self.assertEqual([p.base for p in self.plan("open_drawing", 4).targets], [4])
        self.assertIn("just one", self.plan("open_drawing", 1, 2).message)

    def test_make_cots_texts(self):
        text = logic.make_cots_confirm_text("HCR-00001-001", "Bolt", ["cad/a.SLDPRT"])
        self.assertIn("NOT modified", text)
        self.assertIn("cad/a.SLDPRT", text)
        self.assertIn("- It is checked out", logic.make_cots_problem_text("HCR-00001-001", ["It is checked out"]))

    def test_part_not_in_list(self):
        plan = logic.plan_action("checkout", [PN("HCR", 99, 1)], BY_PN)
        self.assertIn("not in the list", plan.message)

    def test_every_action_is_described(self):
        for action in logic.ALLOWED_KINDS:
            self.assertIn(action, logic.NAME)
            self.assertIn(action, logic.PAST)


def revised(base, working, released, revisions, status="in_work"):
    """A part row with several revisions, e.g. revised(7, "B", "A", {"A": [...], "B": [...]})."""
    r = PartStatus(PN("HCR", base, 1), "Part", status, "Available", "ok", files=list(revisions.get(working, [])),
                   revision=working, released_revision=released, revisions=revisions)
    return r


class TestRevisions(unittest.TestCase):
    A = ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"]
    B = ["cad/HCR-00007-001_B.SLDPRT"]

    def test_open_offers_both_revisions_when_there_is_a_released_and_a_working_one(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        self.assertEqual(logic.open_choices(part), [("B", self.B), ("A", self.A)])        # working first
        self.assertEqual(logic.revision_label(part, "B"), "Rev B (working)")
        self.assertEqual(logic.revision_label(part, "A"), "Rev A (released)")

    def test_open_drawing_only_offers_revisions_that_have_one(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        self.assertEqual(logic.open_choices(part, drawing=True), [("A", self.A)])          # no prompt needed
        self.assertEqual(logic.open_message(part, drawing=True), "")
        only_b = revised(7, "B", "A", {"B": self.B})
        self.assertIn("no drawing", logic.open_message(only_b, drawing=True))

    def test_one_revision_means_no_question(self):
        released = revised(7, "A", "A", {"A": self.A}, status="released")
        self.assertEqual(logic.open_choices(released), [("A", self.A)])
        self.assertEqual(logic.revision_label(released, "A"), "Rev A (released)")
        working_only = revised(7, "A", "", {"A": self.A})
        self.assertEqual(logic.open_choices(working_only), [("A", self.A)])
        self.assertEqual(logic.revision_label(working_only, "A"), "Rev A (working)")

    def test_released_revision_is_opened_when_the_working_one_has_no_files_yet(self):
        part = revised(7, "B", "A", {"A": self.A})
        self.assertEqual(logic.open_choices(part), [("A", self.A)])

    def test_released_view_includes_a_part_with_a_released_revision_while_a_new_one_is_in_work(self):
        part = revised(7, "B", "A", {"A": self.A, "B": self.B})
        plain = revised(8, "A", "", {"A": self.A})
        self.assertEqual(logic.filter_rows([part, plain], view="Released"), [part])

    def test_revision_rows_for_the_history_window(self):
        record = registry.Record(pn=PN("HCR", 7, 1), name="Part", created_by="Alex", created_at="2026-10-01T10:00:00Z",
                                 revision="B", released_revision="A")
        record.history = [{"event": "released", "by": "Jo", "at": "2026-10-02T10:00:00Z", "revision": "A"}]
        rows = logic.revision_rows(record, {"A": self.A, "B": self.B})
        self.assertEqual([r[:2] for r in rows], [("B", "In work"), ("A", "Released")])
        self.assertIn("by Jo", rows[1][2])
        self.assertIn("DRW, PRT", rows[1][2])
        record.released_revision = "B"
        record.status = "released"
        record.history.append({"event": "released", "by": "Bea", "at": "2026-10-09T10:00:00Z", "revision": "B"})
        self.assertEqual([r[:2] for r in logic.revision_rows(record, {})],
                         [("B", "Released"), ("A", "Released (superseded)")])


class TestSortOrder(unittest.TestCase):
    def test_numbers_sort_as_numbers_and_capitals_are_ignored(self):
        values = ["b10", "B9", "a", "b2"]
        self.assertEqual([values[i] for i in logic.sort_order(values)], ["a", "b2", "B9", "b10"])
        self.assertEqual([values[i] for i in logic.sort_order(values, reverse=True)],
                         ["b10", "B9", "b2", "a"])

    def test_blanks_always_come_last(self):
        values = ["", "PRT", " ", "ASM, DRW"]
        self.assertEqual([values[i] for i in logic.sort_order(values)], ["ASM, DRW", "PRT", "", " "])
        self.assertEqual([values[i] for i in logic.sort_order(values, True)], ["PRT", "ASM, DRW", "", " "])

    def test_equal_values_keep_their_order(self):
        self.assertEqual(logic.sort_order(["x", "x", "x"]), [0, 1, 2])
        self.assertEqual(logic.sort_order(["x", "x", "x"], True), [0, 1, 2])

    def test_mixed_text_and_numbers_do_not_crash(self):
        self.assertEqual(len(logic.sort_order(["10", "abc", "9", "2x", "x2"])), 5)


class TestBatchAndSummary(unittest.TestCase):
    def test_run_batch_carries_on_after_a_failure(self):
        def func(pn):
            if pn == "bad":
                raise LitterboxError("nope")
            return pn.upper()
        done, failed = logic.run_batch(["a", "bad", "c"], func)
        self.assertEqual(done, [("a", "A"), ("c", "C")])
        self.assertEqual(failed, [("bad", "nope")])

    def test_run_batch_does_not_hide_programming_errors(self):
        with self.assertRaises(ZeroDivisionError):
            logic.run_batch([1], lambda pn: 1 / 0)

    def test_summary(self):
        self.assertEqual(logic.summary("checkout", 1), "Checked out 1 part")
        self.assertEqual(logic.summary("checkout", 3), "Checked out 3 parts")
        self.assertEqual(logic.summary("checkin", 2, failed=1), "Checked in 2 parts, 1 failed")
        self.assertEqual(logic.summary("checkout", 1, skipped=2), "Checked out 1 part, skipped 2")
        self.assertEqual(logic.summary("checkout", 0, failed=2), "Could not check out 2 parts")
        self.assertEqual(logic.summary("save", 1), "Saved progress on 1 part")


class TestIcon(unittest.TestCase):
    def test_names(self):
        self.assertEqual(logic.icon_filename(), "litterbox_icon_white.ico")
        self.assertEqual(logic.icon_filename("black"), "litterbox_icon_black.ico")
        self.assertEqual(logic.icon_filename(" Black "), "litterbox_icon_black.ico")
        for odd in ("", None, "purple", 5):
            self.assertEqual(logic.icon_filename(odd), "litterbox_icon_white.ico")

    def test_find_icon_prefers_the_choice_then_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertIsNone(logic.find_icon(folder))
            self.assertIsNone(logic.find_icon(folder / "missing"))
            (folder / "litterbox_icon_black.ico").write_bytes(b"x")
            self.assertEqual(logic.find_icon(folder).name, "litterbox_icon_black.ico")      # only one exists
            (folder / "litterbox_icon_white.ico").write_bytes(b"x")
            self.assertEqual(logic.find_icon(folder).name, "litterbox_icon_white.ico")      # default is white
            self.assertEqual(logic.find_icon(folder, "black").name, "litterbox_icon_black.ico")
            (folder / "litterbox_icon_white.ico").unlink()
            self.assertEqual(logic.find_icon(folder, "white").name, "litterbox_icon_black.ico")


class TestUnchangedParts(unittest.TestCase):
    @staticmethod
    def report(has_changes, unchanged=()):
        return ChangeReport(has_changes, [], list(unchanged), False, False)

    def test_only_parts_without_changes_are_listed(self):
        a, b, c = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)
        reports = [
            (a, self.report(False, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"])),
            (b, self.report(True, ["cad/HCR-00002-001_A.SLDDRW"])),      # part changed, drawing didn't: no prompt
            (c, self.report(False)),
        ]
        self.assertEqual(logic.parts_without_changes(reports), [
            (a, ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]),
            (c, []),
        ])
        self.assertEqual(logic.parts_without_changes([]), [])

    def test_dialog_lines(self):
        unchanged = [
            (PN("HCR", 1, 1), ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]),
            (PN("HCR", 3, 1), []),
        ]
        self.assertEqual(logic.unchanged_lines(unchanged), [
            "HCR-00001-001", "    HCR-00001-001_A.SLDDRW", "    HCR-00001-001_A.SLDPRT",
            "HCR-00003-001", "    (no CAD files yet)",
        ])


class TestMessages(unittest.TestCase):
    def test_cad_changes_only_lists_cad_files(self):
        paths = ["cad/HCR-00001-001_A.SLDPRT", "PN-logs/HCR-00001-001.yaml", "cad/HCR-00002-001_A.SLDDRW"]
        self.assertEqual(logic.cad_changes(paths), ["HCR-00001-001_A.SLDPRT", "HCR-00002-001_A.SLDDRW"])
        self.assertEqual(logic.cad_changes(["PN-logs/x.yaml"]), [])

    def test_cad_changes_limit(self):
        names = logic.cad_changes([f"cad/HCR-{n:05d}-001.SLDPRT" for n in range(1, 21)], limit=3)
        self.assertEqual(len(names), 4)
        self.assertEqual(names[-1], "... and 17 more")

    def test_shorten(self):
        self.assertEqual(logic.shorten("  short  "), "short")
        long_text = logic.shorten("x" * 5000, limit=100)
        self.assertLess(len(long_text), 200)
        self.assertIn("full text is in the log", long_text)


class TestHistory(unittest.TestCase):
    def test_time_formatting(self):
        self.assertEqual(logic.to_display_time("2026-10-05T14:02:41Z", local=False), "2026-10-05 14:02")
        self.assertEqual(logic.to_display_time("garbage"), "garbage")
        self.assertRegex(logic.to_display_time("2026-10-05T14:02:41Z"), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_rows_are_newest_first_with_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = registry.create_record(tmp, PN("HCR", 1, 1), "Front upright", "Alex")
            files = ["cad/HCR-00001-001_A.SLDPRT", "cad/HCR-00001-001_A.SLDDRW"]
            registry.record_checkout(record, "Alex", files)
            registry.record_checkin(record, "Alex", files[:1], "Added fillet")
            registry.mark_released(record, "Jo", files)
            registry.mark_reopened(record, "Jo", "Bore wrong")
        rows = logic.format_history(record, local=False)
        self.assertEqual([r[2] for r in rows], ["Unreleased", "Released", "Checked in", "Checked out", "Created"])
        self.assertEqual(rows[0][1:], ("Jo", "Unreleased", "Bore wrong"))
        self.assertEqual(rows[2][3], "Added fillet  -  HCR-00001-001_A.SLDPRT")
        self.assertEqual(rows[3][3], "HCR-00001-001_A.SLDPRT, HCR-00001-001_A.SLDDRW")
        self.assertEqual(rows[4][3], "")


class TestSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_defaults_when_no_file(self):
        self.assertEqual(settings.load(self.dir / "nope.yaml"), settings.DEFAULTS)

    def test_round_trip_creates_folders(self):
        path = self.dir / "deep" / "settings.yaml"
        self.assertTrue(settings.save({"repo": r"D:\Vaults\fsae"}, path))
        self.assertEqual(settings.load(path)["repo"], r"D:\Vaults\fsae")
        self.assertNotIn("\r", path.read_text(encoding="utf-8"))

    def test_broken_files_fall_back_to_defaults(self):
        path = self.dir / "settings.yaml"
        for text in ("just: [broken\n", "- a list\n- not a dict\n", ""):
            path.write_text(text, encoding="utf-8")
            self.assertEqual(settings.load(path), settings.DEFAULTS)

    def test_unwritable_location_does_not_crash(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        self.assertFalse(settings.save({"repo": "x"}, blocker / "settings.yaml"))
        settings.append_log("hello", blocker / "logs" / "litterbox.log")     # must not raise

    def test_log_lines_and_rotation(self):
        path = self.dir / "logs" / "litterbox.log"
        settings.append_log("first\nsecond", path)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in lines], ["first", "second"])
        old_limit = settings.MAX_LOG_BYTES
        settings.MAX_LOG_BYTES = 10
        try:
            settings.append_log("third", path)
        finally:
            settings.MAX_LOG_BYTES = old_limit
        self.assertTrue(path.with_name("litterbox.log.old").exists())
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)


class TestOrgs(unittest.TestCase):
    def test_known_orgs_ignores_junk(self):
        self.assertEqual(logic.known_orgs({}), {})
        self.assertEqual(logic.known_orgs({"orgs": ["x"]}), {})
        self.assertEqual(logic.known_orgs({"orgs": {"hcr": "C:/a", "SAE": "C:/b", "": "c"}}),
                         {"HCR": "C:/a", "SAE": "C:/b"})

    def test_old_single_repo_settings_migrate(self):
        data = {"repo": "C:/v"}
        self.assertTrue(logic.migrate_settings(data, lambda folder: "HCR"))
        self.assertEqual(logic.known_orgs(data), {"HCR": "C:/v"})
        self.assertEqual(logic.current_org(data), "HCR")
        self.assertFalse(logic.migrate_settings(data, lambda folder: "XXX"))     # already migrated
        self.assertFalse(logic.migrate_settings({"repo": "C:/v"}, lambda folder: None))
        self.assertFalse(logic.migrate_settings({}, lambda folder: "HCR"))

    def test_opens_the_last_org_worked_on(self):
        data = {}
        logic.remember_org(data, "hcr", "C:/a")
        logic.remember_org(data, "SAE", "C:/b")
        self.assertEqual(logic.current_org(data), "SAE")
        data["last_org"] = "HCR"
        self.assertEqual(logic.current_org(data), "HCR")
        data["last_org"] = "GONE"
        self.assertEqual(logic.current_org(data), "HCR")           # falls back to the first
        self.assertIsNone(logic.current_org({}))

    def test_menu_lists_orgs_then_actions(self):
        data = {}
        logic.remember_org(data, "HCR", "C:/a")
        logic.remember_org(data, "SAE", "C:/b")
        self.assertEqual(logic.org_menu_values(data), ["HCR", "SAE", logic.ADD_ORG, logic.CREATE_VAULT, logic.EDIT_ORG])


class TestSearchFields(unittest.TestCase):
    def test_search_matches_name_description_and_import_path(self):
        rows = [row(1, name="Front upright", description="6061 tag: suspension"),
                row(2, name="Valve body", import_path=r"D:\Old\valve_v3.SLDPRT")]
        def found(text):
            return [str(r.pn) for r in logic.filter_rows(rows, text, "All", False)]
        self.assertEqual(found("upright"), ["HCR-00001-001"])
        self.assertEqual(found("SUSPENSION"), ["HCR-00001-001"])
        self.assertEqual(found("valve_v3"), ["HCR-00002-001"])
        self.assertEqual(found("00002"), ["HCR-00002-001"])
        self.assertEqual(found("nothing"), [])


class TestTypedNumbers(unittest.TestCase):
    def test_typed_numbers_must_be_written_in_full(self):
        self.assertEqual(logic.parse_typed_number("00002", "part number", 5), 2)
        self.assertEqual(logic.parse_typed_number(" 10001 ", "part number", 5), 10001)
        self.assertEqual(logic.parse_typed_number("001", "variant number", 3), 1)
        for blank in ("", "  ", None):
            self.assertIsNone(logic.parse_typed_number(blank, "part number", 5))
        for bad in ("2", "0002", "000002", "abcde", "1.234", "-0002", "\u00b2\u00b2\u00b2\u00b2\u00b2", "00000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                logic.parse_typed_number(bad, "part number", 5)
        with self.assertRaises(ValueError) as ctx:
            logic.parse_typed_number("2", "part number", 5)
        self.assertIn("exactly 5 digits", str(ctx.exception))
        self.assertIn("00001", str(ctx.exception))
        with self.assertRaises(ValueError):
            logic.parse_typed_number("1", "variant number", 3)
        self.assertEqual(logic.parse_typed_number("000042", "part number", 6), 42)    # other digit counts

    def test_digit_count_boxes(self):
        self.assertEqual(logic.parse_digit_count(" 5 ", "part number digits", 1, 9), 5)
        for bad in ("", "0", "10", "x", "-1", "2.5"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                logic.parse_digit_count(bad, "part number digits", 1, 9)

    def test_in_use_text_names_the_part(self):
        from create import NumberCheck
        self.assertEqual(logic.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "Front upright", "in_work")),
                         "Front upright")
        self.assertEqual(logic.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "Old bracket", "void")),
                         "Old bracket (void)")
        self.assertEqual(logic.in_use_text(NumberCheck(PN("HCR", 1, 1), True, "", "")), "(no name)")


class TestNewNumberHelpers(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(logic.parse_number(" 42 ", "part number"), 42)
        self.assertEqual(logic.parse_number("007", "variant number", maximum=999), 7)
        for bad in ("", "  ", "abc", "4.5", "-3", "\u00b2", "0"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                logic.parse_number(bad, "part number")
        with self.assertRaises(ValueError) as ctx:
            logic.parse_number("1000", "variant number", maximum=999)
        self.assertIn("999", str(ctx.exception))

    def test_parse_optional_number_treats_an_empty_box_as_use_the_suggestion(self):
        for blank in ("", "   ", None):
            self.assertIsNone(logic.parse_optional_number(blank, "part number"))
        self.assertEqual(logic.parse_optional_number(" 12 ", "part number"), 12)
        self.assertEqual(logic.parse_optional_number("005", "variant number", maximum=999), 5)
        for bad in ("x", "0", "1000"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                logic.parse_optional_number(bad, "variant number", maximum=999)

    def test_variant_lines(self):
        import registry
        with tempfile.TemporaryDirectory() as tmp:
            registry.create_record(tmp, PN("HCR", 5, 1), "Left", "Alex")
            registry.create_record(tmp, PN("HCR", 5, 2), "Right", "Alex")
            records = registry.load_variants(tmp, 5)
        records[1].status = "void"
        self.assertEqual(logic.variant_lines(records), ["HCR-00005-001   Left", "HCR-00005-002  [void]   Right"])
        self.assertEqual(logic.variant_lines([]), [])


class TestReviseText(unittest.TestCase):
    def test_void_problem(self):
        class R: pn = "X"; released_revision = "A"
        class N: pn = "X"; released_revision = ""
        self.assertIn("Cancel Revision", logic.void_problem(R()))
        self.assertEqual(logic.void_problem(N()), "")

    def test_revise_texts(self):
        from types import SimpleNamespace as S
        plan = S(pn="X", name="Bracket", revision="A", new_revision="B",
                 copies=[("cad/a_A.SLDPRT", "cad/a_B.SLDPRT")], kept=["cad/a.pdf"])
        t = logic.revise_confirm_text(plan)
        self.assertIn("Rev B", t); self.assertIn("a_B.SLDPRT", t); self.assertIn("a.pdf", t)
        self.assertIn("- no", logic.revise_problem_text("X", ["- no"]).replace("- - ", "- "))

    def test_cancel_texts(self):
        from types import SimpleNamespace as S
        plan = S(pn="X", name="Bracket", revision="B", back_to="A",
                 moves=[("cad/a_B.SLDPRT", "cancelled-revs/CANCELLED_a_B.SLDPRT")])
        t = logic.cancel_confirm_text(plan)
        self.assertIn("CANCELLED_a_B.SLDPRT", t); self.assertIn("back to Rev A", t)
        self.assertIn("can't be cancelled", logic.cancel_problem_text("X", ["why"]))

    def test_allowed_kinds(self):
        self.assertEqual(logic.ALLOWED_KINDS["revise"], {"released"})
        self.assertIn("cancel_revision", logic.ALLOWED_KINDS)


class TestReferenceText(unittest.TestCase):
    def use(self, **kw):
        from types import SimpleNamespace as S
        values = dict(parent=PN("HCR", 2, 1), parent_revision="A", parent_name="Frame", parent_status="in_work",
                      child=PN("HCR", 1, 1), child_revision="A", child_name="Upright", latest_released="B",
                      state_text="Newer revision released (Rev B)", replaceable=True)
        values.update(kw)
        return S(**values)

    def test_tables(self):
        (iid, values, can), = logic.uses_table([self.use()])
        self.assertEqual((iid, can, values[0], values[1], values[3], values[4]),
                         ("0", True, logic.CHECKED, "00001-001", "A", "B"))
        (iid, values, can), = logic.used_in_table([self.use(replaceable=False, parent_status="released")])
        self.assertEqual((can, values[0], values[1], values[4], values[5]), (False, "", "00002-001", "Released", "A"))

    def test_toggled(self):
        self.assertEqual(logic.toggled(logic.CHECKED), logic.UNCHECKED)
        self.assertEqual(logic.toggled(logic.UNCHECKED), logic.CHECKED)
        self.assertEqual(logic.toggled(""), "")

    def test_release_text_shows_warnings(self):
        from types import SimpleNamespace as S
        plan = S(pn=PN("HCR", 2, 1), name="Frame", files=["cad/a.SLDASM"], warnings=["It uses X Rev A."])
        text = logic.release_confirm_text(plan)
        self.assertIn("WARNING", text); self.assertIn("It uses X Rev A.", text)
        plan.warnings = []
        self.assertNotIn("WARNING", logic.release_confirm_text(plan))

    def test_stale_open_text_and_replace_summary(self):
        self.assertIn("Rev B is released", logic.stale_open_text(PN("HCR", 2, 1), [self.use()]))
        from references import ReplaceResult
        text, problems = logic.replace_summary([ReplaceResult(PN("HCR", 2, 1), "done", "ok"),
                                                ReplaceResult(PN("HCR", 3, 1), "skipped", "Checked out by Bea.")])
        self.assertTrue(problems)
        self.assertIn("1 of 2", text); self.assertIn("Checked out by Bea.", text)
        self.assertFalse(logic.replace_summary([ReplaceResult(PN("HCR", 2, 1), "done")])[1])

    def test_history_shows_references(self):
        record = registry.Record(pn=PN("HCR", 2, 1), name="x", created_by="a", created_at="t")
        registry.add_event(record, "checked_in", "Alex", files=["cad/a.SLDASM"], references=["HCR-00001-001_A"])
        self.assertIn("uses HCR-00001-001_A", logic.format_history(record)[0][3])

    def test_outdated_note_and_update_summary(self):
        pn = PN("HCR", 2, 1)
        self.assertEqual(logic.outdated_note(pn, False, []), "")
        self.assertIn("00002-001", logic.outdated_note(pn, True, []))
        self.assertIn("2 other assemblies", logic.outdated_note(pn, False, [1, 2]))
        text, problems = logic.update_summary({pn: "updated", PN("HCR", 3, 1): "skipped: checked out by Bea."})
        self.assertTrue(problems)
        self.assertIn("1 of 2", text); self.assertIn("checked out by Bea", text)
        self.assertFalse(logic.update_summary({pn: "unchanged"})[1])

    def test_references_button_works_on_any_downloaded_part(self):
        self.assertIn("released", logic.ALLOWED_KINDS["references"])
        self.assertIn("unclaimed", logic.ALLOWED_KINDS["references"])


class TestTeamText(unittest.TestCase):
    def setUp(self):
        import people
        self.people = people
        self.d = people.Directory([people.Person("alex", "Alex Smith", "a@x.com", ["alexs"], people.OWNER, ["Quality"]),
                                   people.Person("bea", "Bea", "", [], people.MEMBER, [], False, ["ssh-ed25519 AAAA"])],
                                  ["Quality"])

    def test_banner(self):
        p = self.people
        self.assertEqual(logic.identity_banner(p.Identity(p.LEGACY))[1], "normal")
        text, tone = logic.identity_banner(p.resolve(self.d, "alexs"))
        self.assertEqual((tone, "Alex Smith" in text, "Owner" in text, "Quality" in text), ("normal", True, False, False))
        for host in ("stranger", "", ):
            self.assertEqual(logic.identity_banner(p.resolve(self.d, host))[1], "warn")
        self.assertEqual(logic.identity_banner(p.Identity(p.INACTIVE))[1], "warn")

    def test_people_table(self):
        rows = logic.people_table(self.d)
        self.assertEqual(rows[0], ("alex", ("Alex Smith", "a@x.com", "Owner", "Quality", "Yes", "alexs", "")))
        self.assertEqual(rows[1][1][4:], ("No", "", 1))

    def test_lists_and_ids(self):
        self.assertEqual(logic.split_list("a, b\nc,, "), ["a", "b", "c"])
        self.assertEqual(logic.suggest_person_id("Alex Smith", []), "alex-smith")
        self.assertEqual(logic.suggest_person_id("Alex Smith", ["alex-smith", "alex-smith-2"]), "alex-smith-3")
        self.assertEqual(logic.suggest_person_id("!!!", []), "person")

    def test_who_am_i(self):
        p = self.people
        self.assertIn("matches Alex Smith", logic.who_am_i_text(p.resolve(self.d, "ALEXS")))
        self.assertIn("not on this vault's team list", logic.who_am_i_text(p.resolve(self.d, "stranger")))
        self.assertIn("no team list yet", logic.who_am_i_text(p.Identity(p.LEGACY, "x")))

    def test_person_form(self):
        form = {"name": " Cy  Ng ", "email": "cy@x.com", "host_names": "cyng, Cy Ng", "roles": "Quality",
                "keys": "ssh-ed25519 AAA, with comma\nssh-ed25519 BBB", "access": "Member"}
        problem, fields = logic.person_form_result(None, form, ["alex"])
        self.assertEqual(problem, "")
        self.assertEqual((fields["id"], fields["name"], fields["host_names"], fields["access"]),
                         ("cy-ng", "Cy Ng", ["cyng", "Cy Ng"], "member"))
        self.assertEqual(fields["signing_keys"], ["ssh-ed25519 AAA, with comma", "ssh-ed25519 BBB"])
        self.assertNotIn("id", logic.person_form_result("cy", form, [])[1])                # editing: the id stays
        self.assertIn("name", logic.person_form_result(None, dict(form, name=" "), [])[0])
        self.assertIn("email", logic.person_form_result(None, dict(form, email="nope"), [])[0])




class TestRoleHelpers(unittest.TestCase):
    def test_add_role_result(self):
        self.assertEqual(logic.add_role_result("  Welding   Lead ", ["Quality"]), ("", "Welding Lead"))
        self.assertTrue(logic.add_role_result("", [])[0])
        self.assertTrue(logic.add_role_result("a,b", [])[0])
        self.assertIn("already", logic.add_role_result("quality", ["Quality"])[0])

    def test_role_removal_text(self):
        self.assertIn("Remove the role 'Q'", logic.role_removal_text("Q", []))
        t = logic.role_removal_text("Q", ["Ann", "Bob"])
        self.assertIn("Ann, Bob", t)
        self.assertIn("Save", t)

    def test_roles_to_choose(self):
        self.assertEqual(logic.roles_to_choose(["A", "B", "C"], ["b"]), ["A", "C"])


class TestDebugMode(unittest.TestCase):
    def test_off_by_default_and_for_odd_values(self):
        self.assertFalse(settings.is_debug({}))
        self.assertFalse(settings.is_debug({"debug_mode": False}))
        self.assertFalse(settings.is_debug({"debug_mode": "nope"}))
        self.assertFalse(settings.is_debug({"debug_mode": 2}))
        self.assertFalse(settings.is_debug(None))
        self.assertFalse(settings.DEFAULTS["debug_mode"])

    def test_on_when_true(self):
        self.assertTrue(settings.is_debug({"debug_mode": True}))
        self.assertTrue(settings.is_debug({"debug_mode": "True"}))
        self.assertTrue(settings.is_debug({"debug_mode": "yes"}))

    def test_read_from_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.yaml"
            path.write_text("debug_mode: true\n", encoding="utf-8")
            self.assertTrue(settings.is_debug(settings.load(path)))
            self.assertFalse(settings.is_debug(settings.load(Path(d) / "missing.yaml")))


class TestVaultCreatedText(unittest.TestCase):
    def result(self, **changes):
        from types import SimpleNamespace
        base = dict(org="HCR", pushed=True, owner=SimpleNamespace(name="Alex Smith"), team_error="", warnings=[])
        base.update(changes)
        return SimpleNamespace(**base)

    def test_a_complete_set_up(self):
        text = logic.vault_created_text(self.result())
        self.assertIn("The HCR vault is set up and uploaded.", text)
        self.assertIn("Alex Smith is the team's Owner.", text)

    def test_team_trouble_is_explained_and_not_fatal(self):
        text = logic.vault_created_text(self.result(owner=None, team_error="The host didn't answer."))
        self.assertIn("Use Team... to set it up later", text)
        self.assertIn("didn't answer", text)

    def test_local_only_and_warnings(self):
        text = logic.vault_created_text(self.result(pushed=False, warnings=["Mind the gap."]))
        self.assertIn("on this computer only", text)
        self.assertIn("Mind the gap.", text)


class TestWorkflowText(unittest.TestCase):
    def template(self):
        import workflow
        return workflow.Template("release", "T1", [workflow.Row(["Quality"]), workflow.Row(["Manager", "Chief"])])

    def slots(self):
        return [{"roles": ["Quality"], "id": "bea", "name": "Bea Jones"},
                {"roles": ["Manager", "Chief"], "id": "cy", "name": "Cy Day"},
                {"roles": ["Analysis"], "id": "dee", "name": "Dee", "extra": True}]

    def test_the_request_question_lists_parts_and_signers(self):
        text = logic.request_confirm_text("release", [("HCR-00001-001", "Upright"), ("HCR-00002-001", "Arm")],
                                          self.template(), self.slots())
        self.assertIn("Start the Release workflow (T1)", text)
        self.assertIn("  HCR-00001-001  Upright\n  HCR-00002-001  Arm", text)
        self.assertIn("  Quality: Bea Jones\n", text)
        self.assertIn("  Manager or Chief: Cy Day\n", text)
        self.assertIn("  Analysis (extra): Dee", text)
        self.assertIn("as soon as the last person signs", text)

    def test_make_cots_waits_for_a_second_press_and_reasons_and_notes_show(self):
        text = logic.request_confirm_text("make_cots", [("HCR-00001-001", "Upright")], self.template(), self.slots(),
                                          "Because", ["Nobody has Quality."])
        self.assertIn("press the button again", text)
        self.assertIn("Reason: Because", text)
        self.assertIn("Nobody has Quality.", text)

    def test_standard_actions_route_pending_parts_to_their_buttons(self):
        for action in ("open", "open_drawing", "references", "release", "reopen", "void", "make_cots"):
            self.assertIn("pending", logic.ALLOWED_KINDS[action])
        for action in ("checkout", "checkin", "revise", "cancel_revision", "undo"):
            self.assertNotIn("pending", logic.ALLOWED_KINDS[action])

    def test_task_table_detail_and_button_text(self):
        from types import SimpleNamespace
        task = SimpleNamespace(id="ab12", label="HCR-00001-001 +1 more", action="reopen",
                               parts=[("HCR-00001-001", "Upright", "A"), ("HCR-00002-001", "Arm", "A")],
                               requested_by="Alex Smith", requested_at="2026-10-11T00:00:00Z",
                               summary="Unrelease pending 0/1: waiting on Cy", reason="Drawing error",
                               slots=[{"text": "Manager", "name": "Cy", "done": False},
                                      {"text": "Quality", "name": "Bea", "done": True}])
        (iid, values), = logic.tasks_table([task], local=False)
        self.assertEqual(iid, "ab12")
        self.assertEqual(values, ("HCR-00001-001 +1 more", "2 parts", "Unrelease", "Alex Smith", "2026-10-11 00:00",
                                  "Unrelease pending 0/1: waiting on Cy"))
        detail = logic.task_detail(task)
        self.assertIn("HCR-00001-001, HCR-00002-001", detail)
        self.assertIn("… Manager: Cy (waiting)", detail)
        self.assertIn("✓ Quality: Bea", detail)
        self.assertIn("Reason: Drawing error", detail)
        self.assertEqual(logic.tasks_button_text(0), "My Tasks")
        self.assertEqual(logic.tasks_button_text(3), "My Tasks (3)")

    def test_signoff_result_text_is_empty_unless_something_failed(self):
        from types import SimpleNamespace
        self.assertEqual(logic.signoff_result_text(SimpleNamespace(errors={})), ("", False))
        text, warn = logic.signoff_result_text(SimpleNamespace(errors={"HCR-00001-001": "offline"}))
        self.assertTrue(warn)
        self.assertIn("HCR-00001-001: offline", text)

    def test_people_drop_downs(self):
        import people
        directory = people.Directory(
            [people.Person("a", "Alex", "", [], "owner", ["Quality"]), people.Person("b", "Alex", "", [], "member",
                                                                                      ["Manager"]),
             people.Person("c", "Cy", "", [], "member", ["Quality"], active=False)], ["Quality", "Manager"])
        self.assertEqual(logic.row_choices(directory, ["Quality", "Manager"]), [("Alex (a)", "a"), ("Alex (b)", "b")])
        self.assertEqual(logic.row_choices(directory, ["Quality"], "a", False), [])
        self.assertEqual(logic.row_choices(directory, ["Manager"]), [("Alex", "b")])


class TestWorkflowEditor(unittest.TestCase):
    ROLES = ["Responsible Engineer", "Quality", "Manager", "Chief"]

    def templates(self):
        import workflow
        t = {}
        workflow.set_template(t, "release", "T1", [["Responsible Engineer"], ["Quality"]])
        workflow.set_template(t, "release", "T2", [["Responsible Engineer"]])
        return t

    def test_nothing_changed_means_no_ops(self):
        editor = logic.WorkflowEditor(self.templates())
        self.assertFalse(editor.dirty)
        self.assertEqual(editor.ops(), [])
        self.assertEqual(editor.names("release"), ["T1", "T2"])
        self.assertEqual(editor.names("void"), [])

    def test_adding_changing_and_deleting(self):
        editor = logic.WorkflowEditor(self.templates())
        i = editor.add("void", self.ROLES)
        self.assertEqual((editor.names("void"), editor.items["void"][i]["rows"]), (["T1"], [["Responsible Engineer"]]))
        editor.add_row("release", 0, self.ROLES)
        editor.set_role("release", 0, 2, 0, "Manager")
        self.assertEqual(editor.add_or("release", 0, 2, self.ROLES), "Responsible Engineer")
        editor.delete("release", 1)
        self.assertTrue(editor.dirty)
        ops = editor.ops()
        self.assertEqual([(o["op"], o["action"], o["name"]) for o in ops],
                         [("remove", "release", "T2"), ("set", "release", "T1"), ("set", "void", "T1")])
        self.assertEqual(ops[1]["rows"], [["Responsible Engineer"], ["Quality"], ["Manager", "Responsible Engineer"]])
        self.assertEqual(ops[1]["old"], "T1")
        self.assertIsNone(ops[2]["old"])

    def test_renaming_is_a_set_with_the_old_name(self):
        editor = logic.WorkflowEditor(self.templates())
        editor.items["release"][0]["name"] = "Flight"
        (op,) = editor.ops()
        self.assertEqual((op["name"], op["old"]), ("Flight", "T1"))

    def test_the_ops_replay_on_newer_files(self):
        import workflow
        editor = logic.WorkflowEditor(self.templates())
        editor.items["release"][0]["name"] = "Flight"
        editor.delete("release", 1)
        newer = self.templates()
        workflow.set_template(newer, "release", "Other", [["Chief"]])       # someone else's change
        workflow.apply_ops(newer, editor.ops())
        self.assertEqual(list(newer["release"]), ["Flight", "Other"])

    def test_or_rows(self):
        editor = logic.WorkflowEditor(self.templates())
        editor.add_or("release", 0, 0, self.ROLES)
        editor.remove_or("release", 0, 0, 0)
        self.assertEqual(len(editor.items["release"][0]["rows"][0]), 1)
        editor.remove_or("release", 0, 0, 0)                         # the last role can't be removed
        self.assertEqual(len(editor.items["release"][0]["rows"][0]), 1)

    def test_problems(self):
        editor = logic.WorkflowEditor(self.templates())
        self.assertEqual(editor.problem(), "")
        editor.items["release"][1]["name"] = "t1"
        self.assertIn("two Release workflows", editor.problem())
        editor.items["release"][1]["name"] = " "
        self.assertIn("needs a name", editor.problem())
        editor.items["release"][1]["name"] = "T2"
        editor.items["release"][1]["rows"] = []
        self.assertIn("at least one sign-off", editor.problem())
        editor.items["release"][1]["rows"] = [["Chief", "chief"]]
        self.assertIn("same role twice", editor.problem())

    def test_standard_workflows_skip_what_lacks_roles(self):
        editor = logic.WorkflowEditor({})
        added, skipped = editor.add_standard(["Responsible Engineer", "Manager", "Chief"])
        self.assertEqual(added, ["Release T3", "Unrelease T1", "Void T1", "Make COTS T1"])
        self.assertEqual([n for n, _ in skipped], ["Release T1", "Release T2"])
        self.assertEqual(editor.add_standard(["Responsible Engineer", "Manager", "Chief"])[0], [])

    def test_label_for_the_team_window(self):
        self.assertEqual(logic.ops_label([]), "Workflows")
        ops = [{"action": "release"}, {"action": "void"}, {"action": "release"}]
        self.assertEqual(logic.ops_label(ops), "Workflows: Release, Void")


class TestWorkflowHistory(unittest.TestCase):
    def history(self, *events):
        import registry
        from pn import parse
        record = registry.Record(parse("HCR-00001-001"), "Upright", "Alex", "2026-10-11T00:00:00Z")
        for event in events:
            record.history.append(dict({"by": "Bea", "at": "2026-10-11T01:00:00Z", "revision": "A"}, **event))
        return logic.format_history(record, local=False)

    def test_labels_and_details(self):
        rows = self.history(
            {"event": "release_requested", "waiting_on": ["Quality (0 of 1)"]},
            {"event": "release_signed", "roles": ["Quality"], "comment": "ok"},
            {"event": "release_rejected", "reason": "Missing tolerance", "signed": ["Alex Smith"]},
            {"event": "release_withdrawn", "reason": "Wrong rev"},
            {"event": "released", "signoffs": ["Alex Smith", "Bea Jones"]},
            {"event": "released", "override": True, "reason": "Urgent"})
        by_label = {r[2]: r[3] for r in rows}
        self.assertEqual(by_label["Release requested"], "needs Quality (0 of 1)")
        self.assertEqual(by_label["Signed off"], "ok  -  as Quality")
        self.assertEqual(by_label["Release rejected"], "Missing tolerance  -  had been signed by Alex Smith")
        self.assertEqual(by_label["Request withdrawn"], "Wrong rev")
        self.assertEqual(by_label["Released"], "signed off by Alex Smith, Bea Jones")
        self.assertEqual(by_label["Released (Admin override)"], "Urgent")


class TestTicks(unittest.TestCase):
    A, B, C = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)

    def test_actions_that_change_things_use_only_the_selected_boxes(self):
        for action in ("checkout", "checkin", "save", "undo", "release", "edit", "revise", "void"):
            self.assertEqual(logic.choose_targets(action, [self.A, self.B], [self.C]), [self.A, self.B])
            self.assertEqual(logic.choose_targets(action, [], [self.C]), [])

    def test_looking_at_a_part_uses_the_highlighted_row(self):
        for action in ("open", "open_drawing", "references"):
            self.assertEqual(logic.choose_targets(action, [self.A, self.B], [self.C]), [self.C])

    def test_looking_falls_back_to_the_only_selected_part(self):
        self.assertEqual(logic.choose_targets("open", [self.A], []), [self.A])
        self.assertEqual(logic.choose_targets("open", [self.A, self.B], []), [])

    def test_row_tags(self):
        self.assertEqual(logic.row_tags("mine", False), ("mine",))
        self.assertEqual(logic.row_tags("mine", True), ("mine", "ticked"))

    def test_undo_prompt_lists_each_part_on_its_own_line(self):
        text = logic.undo_prompt([self.A, self.B])
        self.assertTrue(text.startswith("This will discard changes and release the lock on these parts:"))
        self.assertIn(f"\n{self.A}\n{self.B}\n", text)
        self.assertTrue(text.endswith("Continue?"))

    def test_the_banner_shows_only_the_name(self):
        import people
        who = people.Person("bea", "Bea Jones", "", ["Bea"], "member", ["Quality"])
        self.assertEqual(people.Identity.describe(type("I", (), {"state": people.OK, "person": who})()),
                         "Bea Jones")

    def test_tick_text(self):
        self.assertEqual(logic.tick_text(0), "Nothing selected.")
        self.assertTrue(logic.tick_text(1).startswith("1 part selected."))
        self.assertTrue(logic.tick_text(3).startswith("3 parts selected."))

    def test_person_unchanged(self):
        import people
        who = people.Person("bea", "Bea", "b@x.com", ["Bea"], "member", ["Quality"])
        same = {"name": "Bea", "email": "b@x.com", "host_names": ["Bea"], "access": "member", "roles": ["Quality"]}
        self.assertTrue(logic.person_unchanged(who, same))
        self.assertFalse(logic.person_unchanged(who, dict(same, roles=[])))
        self.assertFalse(logic.person_unchanged(who, dict(same, name="Bea J")))


class TestButtonStates(unittest.TestCase):
    P = {r.pn.base: r.pn for r in ROWS}                 # base number -> PN (1 ok, 2 mine, 3 theirs, 4 released, 5 void, 6 stray)

    def states(self, ticked=(), highlighted=()):
        return logic.button_states([self.P[b] for b in ticked], [self.P[b] for b in highlighted], BY_PN)

    def test_nothing_selected_greys_everything(self):
        self.assertFalse(any(self.states().values()))

    def test_one_available_part(self):
        s = self.states(ticked=[1])
        self.assertTrue(s["Check Out"])
        self.assertTrue(s["Release"] and s["Void"] and s["Make COTS"])
        self.assertFalse(s["Check In"] or s["Undo Checkout"] or s["Save Progress"] or s["Edit Details"])
        self.assertFalse(s["Revise"] or s["Unrelease"])

    def test_one_checked_out_part_in_the_selection_greys_check_out(self):
        self.assertFalse(self.states(ticked=[1, 2])["Check Out"])
        self.assertTrue(self.states(ticked=[1, 3])["Check Out"] is False)

    def test_check_in_needs_every_part_to_be_yours(self):
        self.assertTrue(self.states(ticked=[2])["Check In"])
        self.assertFalse(self.states(ticked=[2, 1])["Check In"])

    def test_revise_and_unrelease_need_released_parts(self):
        s = self.states(ticked=[4])
        self.assertTrue(s["Revise"] and s["Unrelease"])
        self.assertFalse(s["Check Out"] or s["Release"])
        self.assertFalse(self.states(ticked=[1])["Revise"])

    def test_single_part_buttons_grey_with_two_parts(self):
        self.assertTrue(self.states(ticked=[2])["Edit Details"])
        both = logic.button_states([self.P[4], self.P[1]], [], BY_PN)
        self.assertFalse(both["Revise"] or both["Edit Details"])

    def test_looking_buttons_follow_the_highlight(self):
        s = self.states(ticked=[1, 2], highlighted=[3])
        self.assertTrue(s["Open"] and s["Open Drawing"] and s["References..."] and s["History"])
        self.assertFalse(s["Check In"])                          # the changing buttons ignore the highlight
        self.assertFalse(self.states(ticked=[1, 2])["Open"])      # two ticks, nothing highlighted
        self.assertTrue(self.states(ticked=[1])["History"])       # one tick stands in for a highlight

    def test_void_parts_can_be_looked_at_but_not_changed(self):
        s = self.states(ticked=[5])
        self.assertTrue(s["Open"])
        self.assertFalse(s["Check Out"] or s["Release"] or s["Void"])

    def test_the_unrelease_button_uses_the_reopen_action(self):
        self.assertEqual(logic.BUTTON_ACTIONS["Unrelease"], "reopen")
        self.assertEqual(logic.NAME["reopen"], "unrelease")
        self.assertEqual(logic.PAST["reopen"], "Unreleased")


class TestShiftRange(unittest.TestCase):
    def test_range_either_direction(self):
        shown = ["a", "b", "c", "d"]
        self.assertEqual(logic.range_between(shown, "b", "d"), ["b", "c", "d"])
        self.assertEqual(logic.range_between(shown, "d", "b"), ["b", "c", "d"])

    def test_no_anchor_is_just_the_row(self):
        self.assertEqual(logic.range_between(["a", "b"], None, "b"), ["b"])
        self.assertEqual(logic.range_between(["a", "b"], "gone", "b"), ["b"])

    def test_shift_held(self):
        from types import SimpleNamespace
        self.assertTrue(logic.shift_held(SimpleNamespace(state=0x1)))
        self.assertTrue(logic.shift_held(SimpleNamespace(state=0x9)))
        self.assertFalse(logic.shift_held(SimpleNamespace(state=0x8)))


if __name__ == "__main__":
    unittest.main()
