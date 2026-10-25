"""Tests for projects: the number blocks (core/projects.py), skipping them (core/numbering.py), the record's project
field, the config, the typed digits and the Projects window's words. None of these need git."""

import tempfile
import unittest
from pathlib import Path

from litterbox.core import numbering
from litterbox.core import part_number
from litterbox.core import projects
from litterbox.core.part_number import PN
from litterbox.gui.logic import list_columns
from litterbox.gui.logic import number_input
from litterbox.gui.logic import project_text
from litterbox.records import record_store
from litterbox.vault import config
from litterbox.vault import config_write


class Digits(unittest.TestCase):
    """Run with 6-digit part numbers, as in the examples, and put the defaults back afterwards."""

    def setUp(self):
        part_number.configure(6, 3)
        self.addCleanup(part_number.configure)


class Blocks(Digits):
    def test_a_prefix_owns_every_number_that_starts_with_it(self):
        rover = projects.Project("Rover", "12")
        self.assertEqual(rover.block(), (120000, 129999))
        self.assertEqual(rover.remaining_digits(), 4)
        self.assertEqual(rover.full_base(34), 120034)
        self.assertTrue(rover.contains(125000) and not rover.contains(130000))
        self.assertEqual(rover.describe(), "Rover (120000 to 129999)")
        self.assertEqual(projects.block("123"), (123000, 123999))

    def test_a_block_of_zeros_never_includes_zero(self):
        self.assertEqual(projects.block("00"), (1, 9999))

    def test_which_project_a_number_is_in(self):
        rules = [projects.Project("Rover", "12"), projects.Project("Lander", "3")]
        self.assertEqual(projects.project_of(345678, rules).name, "Lander")
        self.assertIsNone(projects.project_of(450000, rules))
        outside = projects.outside_blocks(rules)
        self.assertTrue(outside(110000))
        self.assertFalse(outside(120000) or outside(399999))

    def test_names_and_prefixes_are_checked(self):
        rules = [projects.Project("Rover", "12")]
        for name, prefix, wanted in (("", "4", "needs a name"), ("None", "4", "no project"), ("rover", "4", "already"),
                                     ("Lander", "", "Enter the digits"), ("Lander", "4a", "digits only"),
                                     ("Lander", "123456", "at most 5"), ("Lander", "1", "overlap"),
                                     ("Lander", "123", "overlap"), ("x" * 41, "4", "at most 40")):
            with self.assertRaises(projects.ProjectError) as caught:
                projects.new_project(name, prefix, rules)
            self.assertIn(wanted, str(caught.exception), (name, prefix))
        self.assertEqual(projects.new_project("  Lander   two ", "13", rules), projects.Project("Lander two", "13"))

    def test_finding_one_by_name(self):
        rules = [projects.Project("Rover", "12")]
        self.assertEqual(projects.find("ROVER", rules).prefix, "12")
        with self.assertRaises(projects.ProjectError):
            projects.find("Boat", rules)

    def test_free_numbers_can_leave_blocks_out(self):
        outside = projects.outside_blocks([projects.Project("Rover", "00")])           # 1 to 9999
        self.assertEqual(numbering.next_base({10000}, 1, outside), 10001)
        self.assertEqual(numbering.free_bases(set(), 2, 999998, outside), [999998, 999999])
        self.assertEqual(numbering.free_bases(set(), 3, 999998, outside), [999998, 999999, 10000])   # loops round, past the block
        self.assertEqual(numbering.next_base({1}), 2)                                  # no test: as before


class RecordsAndConfig(Digits):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        path = config.config_path(self.repo)
        path.parent.mkdir(parents=True)
        path.write_text("org: HCR\npn_base_digits: 6\n", encoding="utf-8")

    def test_a_record_keeps_its_project_and_one_without_has_no_line(self):
        record_store.create_record(self.repo, PN("HCR", 120001, 1), "Wheel", "Alex", project="Rover")
        record_store.create_record(self.repo, PN("HCR", 2, 1), "Bolt", "Alex")
        self.assertEqual(record_store.load(self.repo, PN("HCR", 120001, 1)).project, "Rover")
        self.assertIn("project: Rover", record_store.record_path(self.repo, PN("HCR", 120001, 1)).read_text())
        self.assertNotIn("project", record_store.record_path(self.repo, PN("HCR", 2, 1)).read_text())
        self.assertEqual(record_store.load(self.repo, PN("HCR", 2, 1)).project, "")

    def test_projects_are_saved_with_their_digits_as_text_and_need_this_version(self):
        from litterbox import version
        self.assertEqual(config.get_projects(self.repo), [])
        config_write.set_values(self.repo, projects=[projects.Project("Rover", "05")])
        text = config.config_path(self.repo).read_text()
        self.assertIn("prefix: '05'", text)
        self.assertEqual(config.get_projects(self.repo), [projects.Project("Rover", "05")])
        self.assertEqual(config.load(self.repo)["min_litterbox_version"], version.release())

    def test_a_hand_edit_that_overlaps_is_reported(self):
        config.config_path(self.repo).write_text(
            "org: HCR\npn_base_digits: 6\nprojects:\n- {name: A, prefix: '12'}\n- {name: B, prefix: '1'}\n")
        with self.assertRaises(config.ConfigError) as caught:
            config.get_projects(self.repo)
        self.assertIn("overlap", str(caught.exception))

    def test_overlapping_projects_are_never_written(self):
        with self.assertRaises(config.ConfigError):
            config_write.set_values(self.repo, projects=[projects.Project("A", "12"), projects.Project("B", "1")])


class TypedDigits(Digits):
    def test_only_the_digits_after_the_prefix_are_typed(self):
        rover = projects.Project("Rover", "12")
        self.assertEqual(number_input.parse_project_number("0034", rover), 120034)
        self.assertEqual(number_input.parse_project_number("0000", rover), 120000)        # 120000 is a part number
        self.assertIsNone(number_input.parse_project_number("  ", rover))
        for bad in ("34", "120034", "12a4"):
            with self.assertRaises(ValueError) as caught:
                number_input.parse_project_number(bad, rover)
            self.assertIn("exactly 4 more digits", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            number_input.parse_project_number("0000", projects.Project("Low", "00"))       # 000000 is not
        self.assertIn("The lowest is 000001", str(caught.exception))


class Words(Digits):
    def test_the_preview_says_what_the_digits_give(self):
        rules = [projects.Project("Rover", "12")]
        self.assertEqual(project_text.preview("Lander", "", rules), ("", ""))
        text, kind = project_text.preview("Lander", "34", rules)
        self.assertEqual(kind, "ok")
        self.assertIn("340000 to 349999", text)
        self.assertIn("other 4 digits", text)
        self.assertEqual(project_text.preview("", "1", rules)[1], "error")              # overlaps Rover
        text, kind = project_text.preview("Old", "00", rules, [PN("HCR", 1, 1), PN("HCR", 2, 1)])
        self.assertEqual(kind, "warn")
        self.assertIn("2 parts are already in this block", text)

    def test_the_questions_say_what_happens_to_the_parts(self):
        from litterbox.vault.project_admin import ProjectChange
        self.assertIn("120000 to 129999", project_text.confirm_text("Rover", "12"))
        self.assertEqual(project_text.project_lines([]), ["No projects yet."])
        rover, small = projects.Project("Rover", "12"), projects.Project("Rover", "123")
        pns = [PN("HCR", 120000 + n, 1) for n in range(7)]
        change = ProjectChange(rover, small, [small], {pn: "" for pn in pns}, leaving=pns)
        text = project_text.change_text(change)
        self.assertIn("This changes which parts are in the project.", text)
        self.assertIn("7 parts leave it (no project): HCR-120000-001", text)
        self.assertIn("and 2 more", text)
        self.assertIn("7 records", text)
        gone = project_text.change_text(ProjectChange(rover, None, [], {pns[0]: ""}, leaving=pns[:1]))
        self.assertIn("Delete project Rover", gone)
        self.assertIn("1 part will have no project", gone)
        self.assertIn("freed", gone)
        renamed = ProjectChange(rover, projects.Project("Rover II", "12"), [], {pns[0]: "Rover II"}, renamed=pns[:1])
        self.assertNotIn("changes which parts", project_text.change_text(renamed))
        self.assertIn("1 part is renamed to Rover II", project_text.change_text(renamed))

    def test_project_is_a_column_that_can_be_shown_and_searched(self):
        column = list_columns.BY_KEY["project"]
        self.assertFalse(column.shown)                                 # added from the Columns menu
        row = type("Row", (), {"project": "Rover"})()
        self.assertEqual(column.search_values(row), ("Rover",))
        self.assertIn("Project", list_columns.search_choices(list_columns.shown_keys(["pn", "project"])))


if __name__ == "__main__":
    unittest.main()
