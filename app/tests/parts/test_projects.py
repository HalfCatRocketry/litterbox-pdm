"""Tests for projects against real git repos: adding one (project_admin.add_project), New Part with and without a
project, New Variant, the dialog's checks and creating many at once. Alex is the Owner; Bea is a Member. The vault
has 5-digit part numbers and part HCR-00001-001. They need Linux, macOS or WSL and are skipped on Windows."""

import unittest

from tests.support.vault_fixture import SKIP_ON_WINDOWS
from tests.support.workflow_fixture import Fixture

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import create
from litterbox.parts import create_batch
from litterbox.parts import number_suggestions
from litterbox.parts import part_status
from litterbox.records import record_store
from litterbox.vault import config
from litterbox.vault import project_admin


@SKIP_ON_WINDOWS
class Projects(Fixture, unittest.TestCase):
    def add_rover(self):
        with self.user("Alex"):
            return project_admin.add_project(self.a, "Rover", "12")         # 12000 to 12999

    def test_an_admin_adds_a_project_for_everyone(self):
        project = self.add_rover()
        self.assertEqual(project.block(), (12000, 12999))
        self.assertIn("Projects: added Rover (12000 to 12999)", self.remote_log()[0])
        self.get_latest("Bea")
        self.assertEqual([p.name for p in config.get_projects(self.b)], ["Rover"])

    def test_a_member_may_not_add_one(self):
        with self.user("Bea"):
            with self.assertRaises(LitterboxError):
                project_admin.add_project(self.b, "Rover", "12")
        self.assertEqual(config.get_projects(self.b), [])

    def test_an_overlapping_project_is_refused_even_one_added_by_someone_else_just_now(self):
        self.add_rover()
        with self.user("Alex"):
            with self.assertRaises(LitterboxError) as caught:
                project_admin.add_project(self.a, "Rover two", "1")
        self.assertIn("overlap", str(caught.exception))
        self.assertEqual(self.locks(self.a), {})

    def test_parts_already_in_a_block_are_listed(self):
        self.assertEqual(project_admin.parts_in_block(self.a, "0"), [PN("HCR", 1, 1)])
        self.assertEqual(project_admin.parts_in_block(self.a, "12"), [])

    def test_new_part_in_a_project_takes_the_next_number_in_its_block(self):
        self.add_rover()
        with self.user("Alex"):
            first = create.new_part(self.a, "Wheel", project="Rover")
            second = create.new_part(self.a, "Axle", project="rover")
            self.assertEqual((first, second), (PN("HCR", 12000, 1), PN("HCR", 12001, 1)))
            self.assertEqual(record_store.load(self.a, first).project, "Rover")
            typed = create.new_part(self.a, "Motor", base=12500, project="Rover")
            self.assertEqual(record_store.load(self.a, typed).project, "Rover")
            row = next(r for r in part_status.get_status(self.a) if r.pn == first)
            self.assertEqual(row.project, "Rover")

    def test_no_project_keeps_out_of_every_block(self):
        with self.user("Alex"):
            project_admin.add_project(self.a, "Low", "0")                     # 1 to 9999 (part 1 is already there)
            pn = create.new_part(self.a, "Bolt")
            self.assertEqual(pn, PN("HCR", 10000, 1))
            self.assertEqual(record_store.load(self.a, pn).project, "")
            with self.assertRaises(LitterboxError) as caught:
                create.new_part(self.a, "Typed", base=5)
            self.assertIn("is in project Low", str(caught.exception))
            self.assertEqual(number_suggestions.suggest_part_number(self.a), 10001)

    def test_a_number_outside_the_chosen_project_is_refused(self):
        self.add_rover()
        with self.user("Alex"):
            with self.assertRaises(LitterboxError) as caught:
                create.new_part(self.a, "Typed", base=13000, project="Rover")
            self.assertIn("start with 12", str(caught.exception))
            with self.assertRaises(LitterboxError):
                create.new_part(self.a, "Nowhere", project="Boat")

    def test_a_new_variant_is_in_its_part_numbers_project(self):
        self.add_rover()
        with self.user("Alex"):
            create.new_part(self.a, "Wheel", project="Rover")
            variant = create.new_variant(self.a, 12000, "Wheel, wide")
            self.assertEqual(variant, PN("HCR", 12000, 2))
            self.assertEqual(record_store.load(self.a, variant).project, "Rover")

    def test_the_dialogs_checks_follow_the_project(self):
        self.add_rover()
        with self.user("Alex"):
            self.assertEqual(number_suggestions.suggest_numbers(self.a, project="Rover"), (12000, 1))
            self.assertEqual(number_suggestions.check_numbers(self.a, 12345, None, project="Rover").pn,
                             PN("HCR", 12345, 1))
            with self.assertRaises(LitterboxError) as caught:
                number_suggestions.check_numbers(self.a, 12345, None)
            self.assertIn("Choose Rover in Project", str(caught.exception))
            self.assertTrue(number_suggestions.check_numbers(self.a, 1, 1).taken)        # outside every block: as before

    def test_a_full_project_says_so(self):
        with self.user("Alex"):
            project_admin.add_project(self.a, "Tiny", "0000")                 # 1 to 9: part 1 is there
            for n in range(2, 10):
                create.new_part(self.a, f"Part {n}", project="Tiny")
            with self.assertRaises(LitterboxError) as caught:
                create.new_part(self.a, "One more", project="Tiny")
        self.assertIn("Every part number in project Tiny", str(caught.exception))

    def test_many_at_once_keep_out_of_blocks_and_get_the_project_of_a_number_asked_for(self):
        with self.user("Alex"):
            project_admin.add_project(self.a, "Low", "0000")                  # 1 to 9
            pns = create_batch.create_many(self.a, [create_batch.PartSpec("A"), create_batch.PartSpec("B", base=5)])
            self.assertEqual([pn.base for pn in pns], [10, 5])
            self.assertEqual([record_store.load(self.a, pn).project for pn in pns], ["", "Low"])


@SKIP_ON_WINDOWS
class ChangingProjects(Fixture, unittest.TestCase):
    """Rover starts 12 (12000 to 12999) with parts 12000 and 12500; part 13000 has no project."""

    def setUp(self):
        super().setUp()
        with self.user("Alex"):
            project_admin.add_project(self.a, "Rover", "12")
            create.new_part(self.a, "Wheel", project="Rover")
            create.new_part(self.a, "Motor", base=12500, project="Rover")
            create.new_part(self.a, "Loose", base=13000)

    def projects_of(self, repo):
        return {pn.base: record_store.load(repo, pn).project for pn in record_store.list_pns(repo)}

    def test_shrinking_a_project_takes_parts_out_and_says_which_first(self):
        with self.user("Alex"):
            plan = project_admin.plan_change(self.a, "Rover", "Rover", "120")         # 12000 to 12099
            self.assertEqual((plan.leaving, plan.joining, plan.renamed), ([PN("HCR", 12500, 1)], [], []))
            commits = len(self.remote_log())
            project_admin.edit_project(self.a, "Rover", "Rover", "120")
            self.assertEqual(self.projects_of(self.a), {1: "", 12000: "Rover", 12500: "", 13000: ""})
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(record_store.load(self.a, PN("HCR", 12500, 1)).history[-1]["changes"],
                             ["project: 'Rover' -> ''"])
        self.assertEqual(len(self.remote_log()), commits + 1)                         # settings and records together
        self.assertIn("HCR-12500-001: Project Rover changed to Rover (12000 to 12099)", self.remote_log()[0])
        self.get_latest("Bea")
        self.assertEqual([p.prefix for p in config.get_projects(self.b)], ["120"])
        with self.user("Bea"):
            self.assertEqual(create.new_part(self.b, "Free again", base=12501).base, 12501)   # out of every block now

    def test_growing_a_project_takes_parts_in(self):
        with self.user("Alex"):
            project_admin.edit_project(self.a, "Rover", "Rover II", "1")             # 10000 to 19999, and a new name
            self.assertEqual(self.projects_of(self.a), {1: "", 12000: "Rover II", 12500: "Rover II", 13000: "Rover II"})
            self.assertEqual(create.new_part(self.a, "Next", project="Rover II").base, 10000)

    def test_a_new_name_alone_renames_the_parts(self):
        with self.user("Alex"):
            plan = project_admin.plan_change(self.a, "Rover", "Lunar", "12")
            self.assertEqual(sorted(plan.renamed), [PN("HCR", 12000, 1), PN("HCR", 12500, 1)])
            project_admin.edit_project(self.a, "Rover", "Lunar", "12")
            self.assertEqual(self.projects_of(self.a)[12500], "Lunar")

    def test_deleting_a_project_leaves_its_parts_with_none_and_frees_the_block(self):
        with self.user("Alex"):
            project_admin.delete_project(self.a, "Rover")
            self.assertEqual(config.get_projects(self.a), [])
            self.assertEqual(set(self.projects_of(self.a).values()), {""})
            self.assertEqual(create.new_part(self.a, "Anywhere", base=12001).base, 12001)

    def test_a_change_to_a_checked_out_part_is_refused_and_nothing_changes(self):
        from litterbox.parts import checkout
        self.get_latest("Bea")
        with self.user("Bea"):
            checkout.checkout(self.b, PN("HCR", 12500, 1))
        with self.user("Alex"):
            with self.assertRaises(LitterboxError) as caught:
                project_admin.delete_project(self.a, "Rover")
            self.assertIn("HCR-12500-001 (Bea)", str(caught.exception))
            self.assertEqual([p.name for p in config.get_projects(self.a)], ["Rover"])
            self.assertEqual(self.projects_of(self.a)[12000], "Rover")
            project_admin.edit_project(self.a, "Rover", "Rover", "1")     # 12500 stays in: only 13000 joins: fine
            self.assertEqual(self.projects_of(self.a)[13000], "Rover")

    def test_the_new_digits_still_cant_overlap_another_project(self):
        with self.user("Alex"):
            project_admin.add_project(self.a, "Lander", "3")
            with self.assertRaises(LitterboxError) as caught:
                project_admin.plan_change(self.a, "Rover", "Rover", "3")
            self.assertIn("overlap", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
