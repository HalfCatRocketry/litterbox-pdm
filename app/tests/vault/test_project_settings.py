"""Tests for the org's project settings (core/project_settings.py) in a real two-user vault: who may add a project,
the fewest starting digits (Admins may go ahead after a warning, anyone else is refused), whoever adds a project
becomes its Lead, and the settings make the vault need 0.6.4. Alex is the Owner, Bea a Member. With 5-digit part
numbers."""

import unittest

from tests.support.workflow_fixture import Fixture

from litterbox.core import project_settings
from litterbox.errors import LitterboxError
from litterbox.vault import config
from litterbox.vault import project_admin
from litterbox.vault import settings_admin
from litterbox import version


class ProjectSettings(Fixture, unittest.TestCase):
    def settings(self, **values):
        self.do("Alex", settings_admin.edit, **values)
        self.get_latest("Bea")

    def project(self, name):
        self.get_latest("Alex")
        return next(p for p in config.get_projects(self.a) if p.name == name)

    def test_by_default_only_admins_add_projects_and_become_their_lead(self):
        with self.assertRaises(LitterboxError):
            self.do("Bea", project_admin.add_project, "Rover", "12")
        self.do("Alex", project_admin.add_project, "Rover", "12")
        self.assertEqual(self.project("Rover").lead, "alex")

    def test_anyone_may_add_one_when_the_org_allows_and_leads_it(self):
        self.settings(project_creators=project_settings.ANYONE)
        self.do("Bea", project_admin.add_project, "Rover", "12")
        self.assertEqual(self.project("Rover").lead, "bea")
        self.do("Bea", project_admin.add_project, "Lander", "13", {"lead": "alex"})   # or the Lead chosen
        self.assertEqual(self.project("Lander").lead, "alex")
        minimum = config.load(self.a)["min_litterbox_version"]                         # the settings need 0.6.4
        self.assertGreaterEqual(version.parse(minimum), version.parse(project_settings.MIN_LITTERBOX))

    def test_too_few_digits_are_refused_unless_an_admin_goes_ahead(self):
        self.settings(project_creators=project_settings.ANYONE, project_min_digits=3)
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", project_admin.add_project, "Rover", "12", short_ok=True)    # not an Admin
        self.assertIn("at least 3 starting digits", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Alex", project_admin.add_project, "Rover", "12")                  # not warned yet
        self.do("Alex", project_admin.add_project, "Rover", "12", short_ok=True)
        self.do("Bea", project_admin.add_project, "Lander", "130")
        self.get_latest("Alex")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", project_admin.edit_project, "Lander", "Lander", "14")      # new digits too
        self.assertIn("at least 3 starting digits", str(ctx.exception))
        self.do("Alex", project_admin.edit_project, "Lander", "Lander", "14", short_ok=True)
        self.assertEqual(self.project("Lander").prefix, "14")

    def test_back_to_the_defaults_takes_the_lines_out(self):
        self.settings(project_creators=project_settings.ANYONE, project_min_digits=2)
        self.settings(project_creators=project_settings.ADMINS, project_min_digits=0)
        data = config.load(self.a)
        self.assertNotIn("project_creators", data)
        self.assertNotIn("project_min_digits", data)


class Rules(unittest.TestCase):
    def test_settings_are_checked(self):
        self.assertEqual(project_settings.check_creators(None), project_settings.ADMINS)
        self.assertEqual(project_settings.check_min_digits(None, 5), 0)
        self.assertEqual(project_settings.check_min_digits(3, 5), 3)
        for bad in (5, -1, True, "3"):
            with self.assertRaises(project_settings.ProjectError):
                project_settings.check_min_digits(bad, 5)
        with self.assertRaises(project_settings.ProjectError):
            project_settings.check_creators("everyone")

    def test_too_short(self):
        self.assertTrue(project_settings.too_short("12", 3))
        self.assertFalse(project_settings.too_short("123", 3))
        self.assertFalse(project_settings.too_short("1", 0))
        self.assertIn("1,000 part numbers", project_settings.short_text("12", 3, 5))


if __name__ == "__main__":
    unittest.main()
