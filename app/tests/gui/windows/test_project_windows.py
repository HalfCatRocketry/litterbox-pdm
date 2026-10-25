"""Tests for the Projects window and the Project window (gui/dialogs/projects_dialog.py, project_dialog.py): the Lead,
Restrict and Hide, searching the team and adding and removing members, and who gets Edit, Delete and New Project.
The windows are built on stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also
try the real windows."""

import unittest
from types import SimpleNamespace

from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes
from tests.team.test_project_access import ALEX, BEA, CY, TEAM

from litterbox.core import projects
from litterbox.gui.logic import project_team_text

ROVER = projects.with_team(projects.Project("Rover", "12"), "cy", ["bea"], restricted=True)
LANDER = projects.Project("Lander", "13")


class ProjectWindow(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)

    def window(self, project=ROVER, digits_editable=True):
        dialog = self.gui.project_dialog.ProjectDialog(FakeParent(), project, [LANDER], TEAM, digits_editable)
        self.problems = []
        dialog.problem = SimpleNamespace(configure=lambda text: self.problems.append(text))
        return dialog

    def test_it_starts_as_the_project_is(self):
        dialog = self.window()
        self.assertEqual(dialog.lead_var.get(), "Cy Day")
        self.assertEqual(dialog.team(), {"lead": "cy", "members": ["bea"], "restricted": True, "hidden": False, "lead_only_folders": False})
        self.assertEqual(list(dialog.member_list.rows), ["bea"])
        self.assertEqual(list(dialog.team_list.rows), ["alex", "dee"])        # not the Lead, not a member, not off

    def test_search_add_and_remove_members(self):
        dialog = self.window()
        dialog.search_var.set("dee")
        self.assertEqual(list(dialog.team_list.rows), ["dee"])
        dialog.team_list.selection_set("dee")
        dialog._add()
        self.assertEqual(dialog.members, ["bea", "dee"])
        dialog.member_list.selection_set("bea")
        dialog._remove()
        self.assertEqual(dialog.members, ["dee"])
        dialog.member_list.selection_set()
        dialog._remove()
        self.assertIn("Pick members", self.problems[-1])

    def test_hide_ticks_restrict_and_both_need_a_lead(self):
        dialog = self.window(projects.Project("Rover", "12"))
        dialog.hidden_var.set(True)
        dialog._switched()
        self.assertTrue(dialog.restricted_var.get())
        dialog._save()
        self.assertEqual(self.problems[-1], project_team_text.NEEDS_LEAD)
        self.assertIsNone(dialog.result)
        dialog.lead_var.set("Cy Day")
        dialog._lead_changed()
        dialog._save()
        self.assertEqual(dialog.result, {"name": "Rover", "prefix": "12", "team": {
            "lead": "cy", "members": [], "restricted": True, "hidden": True, "lead_only_folders": False},
            "short_ok": False})

    def test_making_someone_the_lead_takes_them_off_the_members(self):
        dialog = self.window()
        dialog.lead_var.set("Bea Jones")
        dialog._lead_changed()
        self.assertEqual(dialog.members, [])
        self.assertIn("cy", dialog.team_list.rows)

    def new(self, admin, answer=True):
        self.box.answer = answer
        dialog = self.gui.project_dialog.ProjectDialog(FakeParent(), None, [LANDER], TEAM, min_digits=3, admin=admin,
                                                       me="bea")
        self.problems = []
        dialog.problem = SimpleNamespace(configure=lambda text: self.problems.append(text))
        dialog.name_var.set("Rover")
        dialog.prefix_var.set("12")
        return dialog

    def test_a_new_projects_lead_starts_as_whoever_adds_it(self):
        self.assertEqual(self.new(admin=False).team()["lead"], "bea")

    def test_too_few_digits_are_refused_for_a_member(self):
        dialog = self.new(admin=False)
        dialog._save()
        self.assertIsNone(dialog.result)
        self.assertIn("at least 3 starting digits", self.problems[-1])

    def test_an_admin_is_warned_and_may_proceed(self):
        asked = []
        test = self

        class Confirm:
            def __init__(self, *args, **kwargs):
                asked.append(kwargs.get("confirm_text"))

            def show(self):
                return test.proceed
        self.gui.project_dialog.confirm_dialogs.ConfirmDialog = Confirm
        self.proceed = False                                        # Cancel
        dialog = self.new(admin=True)
        dialog._save()
        self.assertIsNone(dialog.result)
        self.proceed = True                                         # Proceed
        dialog = self.new(admin=True)
        dialog._save()
        self.assertEqual((asked, dialog.result["short_ok"]), (["Proceed", "Proceed"], True))

    def test_nothing_changed(self):
        dialog = self.window()
        dialog._save()
        self.assertIsNone(dialog.result)
        self.assertTrue(any(c[0] == "showinfo" for c in self.box.calls))


class ProjectsWindow(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())

    def window(self, person, hidden=False):
        rover = projects.with_team(ROVER, "cy", ["bea"], hidden=hidden)
        return self.gui.projects_dialog.ProjectsDialog(FakeParent(), "C:/vault", [rover, LANDER], TEAM, person,
                                                       legacy=False)

    def test_admins_get_everything_leads_their_project_and_others_look(self):
        admin, lead, member = self.window(ALEX), self.window(CY), self.window(BEA)
        self.assertTrue(admin.admin and not lead.admin and not member.admin)
        self.assertEqual([p.name for p in member.projects], ["Rover", "Lander"])

    def test_a_hidden_project_is_listed_only_for_those_who_may_see_it(self):
        dee = next(p for p in TEAM.people if p.id == "dee")
        self.assertEqual([p.name for p in self.window(dee, hidden=True).projects], ["Lander"])
        self.assertEqual([p.name for p in self.window(BEA, hidden=True).projects], ["Rover", "Lander"])

    def test_edit_gives_the_projects_new_team(self):
        dialog = self.window(CY)
        team = {"lead": "cy", "members": ["bea", "dee"], "restricted": True, "hidden": False, "lead_only_folders": False}
        self.gui.projects_dialog.project_dialog.ProjectDialog = lambda *a, **k: SimpleNamespace(
            show=lambda: {"name": "Rover", "prefix": "12", "team": team, "short_ok": False})
        dialog._edit(dialog.projects[0])
        self.assertEqual(dialog.result, ("edit", "Rover", "Rover", "12", team, False))

    def test_new_project_is_for_admins_or_anyone_when_the_org_allows(self):
        self.assertFalse(self.window(BEA).may_add)
        member = self.gui.projects_dialog.ProjectsDialog(FakeParent(), "C:/vault", [LANDER], TEAM, BEA, legacy=False,
                                                         may_add=True)
        self.assertTrue(member.may_add and not member.admin)


if __name__ == "__main__":
    unittest.main()
