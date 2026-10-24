"""Tests for project Leads, members, Restrict and Hide that need no git: the project model (core/projects.py), who may
do what (team/project_access.py), the Project window's words (gui/logic/project_team_text.py) and the paths a hidden
project leaves out (vault/project_visibility.py)."""

import unittest

from litterbox.core import projects
from litterbox.gui.logic import project_team_text
from litterbox.team import project_access
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.vault import project_visibility

ALEX = team_model.Person("alex", "Alex Smith", "alex@x.com", ["Alex"], team_model.OWNER, ["Responsible Engineer"])
BEA = team_model.Person("bea", "Bea Jones", "bea@x.com", ["Bea"], team_model.MEMBER, ["Quality"])
CY = team_model.Person("cy", "Cy Day", "cy@x.com", ["Cy"], team_model.MEMBER, ["Manager"])
DEE = team_model.Person("dee", "Dee Chief", "dee@x.com", ["Dee"], team_model.MEMBER, ["Chief"])
GONE = team_model.Person("gus", "Gus Gone", "gus@x.com", ["Gus"], team_model.MEMBER, ["Quality"], active=False)
TEAM = team_model.Directory([ALEX, BEA, CY, DEE, GONE], ["Responsible Engineer", "Quality", "Manager", "Chief"],
                            superuser_roles=["Chief"])
ROVER = projects.Project("Rover", "12")


class Model(unittest.TestCase):
    def test_team_fields_are_optional_and_round_trip(self):
        rover = projects.with_team(ROVER, "cy", ["bea", "cy", "bea", ""], restricted=True)
        self.assertEqual((rover.lead, rover.members, rover.restricted, rover.hidden), ("cy", ("bea",), True, False))
        data = projects.to_data([ROVER, rover])
        self.assertEqual(data, [{"name": "Rover", "prefix": "12"},
                                {"name": "Rover", "prefix": "12", "lead": "cy", "members": ["bea"],
                                 "restricted": True}])
        self.assertEqual(projects.from_data(data[1:], 6), [rover])

    def test_hidden_is_always_restricted_and_both_need_a_lead(self):
        self.assertTrue(projects.with_team(ROVER, "cy", hidden=True).restricted)
        for flags in ({"restricted": True}, {"hidden": True}):
            with self.assertRaises(projects.ProjectError) as ctx:
                projects.with_team(ROVER, "", ["bea"], **flags)
            self.assertIn("Project Lead", str(ctx.exception))

    def test_the_lead_and_the_members_are_members(self):
        rover = projects.with_team(ROVER, "cy", ["bea"])
        self.assertTrue(rover.is_member("cy") and rover.is_member("bea"))
        self.assertFalse(rover.is_member("alex") or rover.is_member(""))


class Rules(unittest.TestCase):
    def setUp(self):
        self.open = projects.with_team(ROVER, "cy", ["bea"])
        self.restricted = projects.with_team(ROVER, "cy", ["bea"], restricted=True)
        self.hidden = projects.with_team(ROVER, "cy", ["bea"], hidden=True)

    def test_only_members_work_on_a_restricted_project_and_admins_always_may(self):
        for person in (ALEX, BEA, CY, DEE):
            self.assertTrue(project_access.may_work(person, self.open))
            self.assertTrue(project_access.may_work(person, None))
        self.assertEqual([p.id for p in (ALEX, BEA, CY, DEE) if project_access.may_work(p, self.restricted)],
                         ["alex", "bea", "cy"])
        self.assertFalse(project_access.may_work(None, self.restricted))
        self.assertTrue(project_access.may_work(None, self.restricted, legacy=True))     # no team: no rules

    def test_only_members_see_a_hidden_project(self):
        self.assertTrue(project_access.may_see(DEE, self.restricted))
        self.assertFalse(project_access.may_see(DEE, self.hidden))
        self.assertTrue(project_access.may_see(BEA, self.hidden) and project_access.may_see(ALEX, self.hidden))
        self.assertEqual(project_access.visible(DEE, [self.open, self.hidden]), [self.open])

    def test_the_lead_and_admins_edit_a_project(self):
        self.assertEqual([p.id for p in (ALEX, BEA, CY, DEE) if project_access.may_edit(p, self.restricted)],
                         ["alex", "cy"])

    def test_superusers_sign_a_restricted_project_they_can_see(self):
        self.assertTrue(project_access.may_sign(TEAM, DEE, self.restricted))
        self.assertFalse(project_access.may_sign(TEAM, DEE, self.hidden))
        self.assertFalse(project_access.may_sign(TEAM, GONE, self.restricted))
        self.assertEqual([p.id for p in project_access.signers(TEAM, TEAM.people, [self.hidden])],
                         ["alex", "bea", "cy"])

    def test_new_part_offers_only_the_projects_you_may_use(self):
        other = projects.Project("Lander", "13")
        self.assertEqual(project_access.usable(DEE, [self.restricted, other]), [other])
        self.assertEqual(project_access.usable(BEA, [self.restricted, other]), [self.restricted, other])

    def test_the_refusal_names_the_lead(self):
        self.assertEqual(project_access.refusal(TEAM, self.restricted, "check out HCR-120001-001"),
                         "You can't check out HCR-120001-001: project Rover is restricted to its members. Ask Cy Day, "
                         "its Lead, to add you.")


class Words(unittest.TestCase):
    def test_the_lead_menu_offers_active_people_and_keeps_a_switched_off_lead(self):
        self.assertEqual([pid for _label, pid in project_team_text.lead_choices(TEAM)],
                         ["alex", "bea", "cy", "dee"])
        self.assertIn("gus", [pid for _label, pid in project_team_text.lead_choices(TEAM, "gus")])
        choices = project_team_text.lead_choices(TEAM)
        self.assertEqual(project_team_text.lead_label(choices, "cy"), "Cy Day")
        self.assertEqual(project_team_text.lead_label(choices, ""), project_team_text.NO_LEAD)

    def test_search_finds_people_to_add_who_are_not_in_yet(self):
        self.assertEqual([pid for _l, pid in project_team_text.addable(TEAM, "cy", ["bea"])], ["alex", "dee"])
        self.assertEqual([pid for _l, pid in project_team_text.addable(TEAM, "", [], "jones")], ["bea"])
        self.assertEqual([pid for _l, pid in project_team_text.addable(TEAM, "", [], "dee@x")], ["dee"])

    def test_members_and_the_projects_line(self):
        self.assertEqual(project_team_text.member_rows(TEAM, ["bea", "gus", "zed"]),
                         [("Bea Jones", "bea"), ("Gus Gone (switched off)", "gus"), ("zed", "zed")])
        hidden = projects.with_team(ROVER, "cy", ["bea", "dee"], hidden=True)
        self.assertEqual(project_team_text.team_line(TEAM, hidden), "Lead: Cy Day · 2 members · Hidden")
        self.assertEqual(project_team_text.team_line(TEAM, ROVER), "")

    def test_restrict_or_hide_needs_a_lead(self):
        self.assertEqual(project_team_text.problem("", True, False), project_team_text.NEEDS_LEAD)
        self.assertEqual(project_team_text.problem("cy", True, True), "")
        self.assertEqual(project_team_text.problem("", False, False), "")


class Hidden(unittest.TestCase):
    def test_a_hidden_project_leaves_out_its_records_files_and_cancelled_revisions(self):
        self.assertEqual(project_visibility.patterns("HCR", [ROVER]),
                         ["/PN-logs/HCR-12*", "/cad/HCR-12*", "/cad/cancelled-revs/CANCELLED_HCR-12*",
                          "/cancelled-revs/CANCELLED_HCR-12*"])

    def test_only_the_hidden_projects_you_may_not_see(self):
        hidden = projects.with_team(ROVER, "cy", ["bea"], hidden=True)
        restricted = projects.with_team(projects.Project("Lander", "13"), "cy", restricted=True)
        everyone = [hidden, restricted]
        see = lambda person: project_visibility.hidden_from(team_identity.Identity(team_identity.OK, "", person, TEAM),
                                                            everyone)
        self.assertEqual(see(DEE), [hidden])
        self.assertEqual(see(BEA), [])
        self.assertEqual(see(ALEX), [])
        self.assertEqual(project_visibility.hidden_from(team_identity.Identity(team_identity.UNVERIFIED), everyone),
                         [hidden])
        self.assertEqual(project_visibility.hidden_from(team_identity.Identity(team_identity.LEGACY), everyone), [])


if __name__ == "__main__":
    unittest.main()
