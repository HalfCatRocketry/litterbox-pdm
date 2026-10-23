"""Tests for restricted and hidden projects in a real two-user vault (team/project_access.py, vault/project_admin.py,
vault/project_visibility.py): only members work on a restricted project's parts and sign for them, its Lead edits it,
and a hidden project's parts are left out of everyone else's copy. Alex is the Owner, Bea and Cy are Members."""

import subprocess
import unittest
from unittest import mock

from tests.support.vault_fixture import PART, PRT, REC
from tests.support.workflow_fixture import PART2, Fixture

from litterbox import diagnostics
from litterbox.errors import LitterboxError
from litterbox.parts import checkout
from litterbox.parts import create
from litterbox.parts import part_status
from litterbox.parts import undoing
from litterbox.team import team_identity
from litterbox.vault import config
from litterbox.vault import project_admin
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_templates

# With 5-digit part numbers, project Rover (digits 0000) owns 00001 to 00009: both test parts.
TEAM = {"lead": "cy", "members": [], "restricted": True, "hidden": False}


class Restricted(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.second_part()
        self.do("Alex", project_admin.add_project, "Rover", "0000", TEAM)
        for user in ("Bea", "Cy"):
            self.get_latest(user)

    def set_team(self, user, **changes):
        self.get_latest(user)
        self.do(user, project_admin.edit_project, "Rover", "Rover", "0000", dict(TEAM, **changes))
        for name in ("Alex", "Bea", "Cy"):
            self.get_latest(name)

    def test_only_members_change_its_parts(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", checkout.checkout, PART)
        self.assertIn("project Rover is restricted to its members. Ask Cy Day, its Lead", str(ctx.exception))
        self.do("Cy", checkout.checkout, PART)                     # the Lead
        self.do("Cy", undoing.undo_checkout, PART)
        self.do("Alex", checkout.checkout, PART2)                  # the Owner, as an override
        self.do("Alex", undoing.undo_checkout, PART2)
        self.set_team("Cy", members=["bea"])
        self.do("Bea", checkout.checkout, PART)                    # a member now

    def test_only_members_make_its_part_numbers(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", create.new_part, "Bracket", project="Rover")
        self.assertIn("make part numbers in project Rover", str(ctx.exception))
        self.do("Cy", create.new_part, "Bracket", project="Rover")

    def test_only_members_ask_and_are_named_to_sign(self):
        self.set_template()
        self.get_latest("Cy")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.assertIn("restricted", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:          # Bea has Quality, but isn't a member
            self.do("Cy", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.assertIn("Bea Jones can't sign for parts in project Rover", str(ctx.exception))
        self.set_team("Cy", members=["bea"])
        self.do("Cy", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])

    def test_the_lead_edits_it_but_not_its_digits_and_others_not_at_all(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", project_admin.edit_project, "Rover", "Rover", "0000", dict(TEAM, members=["bea"]))
        self.assertIn("Only an Admin or Cy Day can change project Rover", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Cy", project_admin.edit_project, "Rover", "Rover", "000", TEAM)
        self.set_team("Cy", members=["bea"])
        self.do("Cy", project_admin.edit_project, "Rover", "Rover Two", "0000", dict(TEAM, members=["bea"]))
        self.get_latest("Alex")
        rover = config.get_projects(self.a)[0]
        self.assertEqual((rover.name, rover.lead, rover.members, rover.restricted), ("Rover Two", "cy", ("bea",), True))

    def test_restrict_needs_a_lead(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", project_admin.edit_project, "Rover", "Rover", "0000", dict(TEAM, lead=""))
        self.assertIn("Choose a Project Lead", str(ctx.exception))


class Hidden(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.logged = []                                # what went wrong, shown when a check fails
        logging = mock.patch.object(diagnostics, "LOG", lambda text, *a, **k: self.logged.append(str(text)))
        logging.start()
        self.addCleanup(logging.stop)
        self.do("Alex", project_admin.add_project, "Rover", "0000", dict(TEAM, hidden=True))
        with self.user("Bea"):
            team_identity.current(self.b, refresh=True)            # Bea is known in her copy
        self.get_latest("Bea")

    def test_its_parts_are_left_out_of_everyone_elses_copy(self):
        self.assertFalse((self.b / REC).exists(), self.warnings())
        self.assertFalse((self.b / PRT).exists(), self.warnings())
        self.assertNotIn(PART, [row.pn for row in part_status.get_status(self.b)])
        self.assertTrue((self.a / REC).exists())                   # the Owner sees everything

    def test_a_new_member_gets_them_at_the_next_get_latest_and_loses_them_when_taken_off(self):
        self.do("Alex", project_admin.edit_project, "Rover", "Rover", "0000", dict(TEAM, hidden=True, members=["bea"]))
        self.get_latest("Bea")
        self.assertTrue((self.b / REC).exists() and (self.b / PRT).exists(), self.warnings())
        self.do("Alex", project_admin.edit_project, "Rover", "Rover", "0000", dict(TEAM, hidden=True))
        self.get_latest("Bea")
        self.assertFalse((self.b / REC).exists(), self.warnings())

    def warnings(self):
        """Any warning logged, and git's view of Bea's copy: shown when a check fails."""
        logged = [line for line in self.logged if "WARNING" in line or "fail" in line.lower()]
        state = [subprocess.run(["git", *args], cwd=self.b, capture_output=True, text=True).stdout
                 for args in (["config", "--show-origin", "--get-regexp", "sparse|fetchexclude"],
                              ["ls-files", "-t", "-v", "PN-logs", "cad"], ["status", "--short"])]
        return "\n".join(logged or ["(no warnings)"]) + "\n" + "\n".join(state)

    def test_unhiding_brings_them_back(self):
        self.do("Alex", project_admin.edit_project, "Rover", "Rover", "0000", TEAM)
        self.get_latest("Bea")
        self.assertTrue((self.b / REC).exists())
        self.assertIn(PART, [row.pn for row in part_status.get_status(self.b)])


if __name__ == "__main__":
    unittest.main()
