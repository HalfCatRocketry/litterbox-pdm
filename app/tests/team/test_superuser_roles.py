"""Tests for superuser roles in the team file (team_model, team_editing) and the Roles window's Superuser box. The
window is replaced by stand-ins (tests/support/gui_fakes.py), so these check the wiring."""

import unittest

from litterbox.team import team_editing
from litterbox.team import team_model
from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes


def directory(superusers=("Chief",)):
    d = team_model.Directory([team_model.Person("alex", "Alex", "", ["Alex"], team_model.OWNER, ["Chief"]),
                              team_model.Person("bea", "Bea", "", ["Bea"], team_model.MEMBER, ["Quality"])],
                             ["Quality", "Chief"], superuser_roles=list(superusers))
    team_model.validate(d)
    return d


class TeamFile(unittest.TestCase):
    def test_superuser_roles_are_saved_and_read_back(self):
        d = directory()
        data = d.to_dict()
        self.assertEqual(data["superuser_roles"], ["Chief"])
        again = team_model.from_dict(data)
        self.assertEqual((again.superuser_roles, again.extra), (["Chief"], {}))
        self.assertNotIn("superuser_roles", directory(()).to_dict())        # none: no line

    def test_holders_of_a_superuser_role_are_superusers_while_active(self):
        d = directory()
        self.assertTrue(d.is_superuser(d.get("alex")))
        self.assertFalse(d.is_superuser(d.get("bea")))
        d.get("alex").active = False
        self.assertFalse(d.is_superuser(d.get("alex")))

    def test_a_superuser_role_that_is_no_longer_a_role_is_dropped(self):
        d = directory(("chief", "Gone"))                 # an older Litterbox removed "Gone" without knowing
        self.assertEqual(d.superuser_roles, ["Chief"])

    def test_changing_the_roles_keeps_the_superuser_roles_in_step(self):
        d = directory()
        alex = d.get("alex")
        team_editing.set_roles(d, alex, ["Quality", "Chief", "Manager"], superusers=["Manager"])
        self.assertEqual(d.superuser_roles, ["Manager"])
        team_editing.set_roles(d, alex, ["Quality", "Chief"], scrub=True)
        self.assertEqual(d.superuser_roles, [])          # Manager went, so it is no longer a superuser role


class RolesWindow(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.applied = []
        self.window = self.gui.roles_dialog.RolesDialog(
            FakeParent(), ["Quality", "Chief"], lambda role: [], superusers=["Chief"],
            apply=lambda roles, superusers, folders: self.applied.append((roles, superusers)) or "")

    def select(self, role):
        self.window.tree.selection_set(role)
        self.window._selected()

    def test_the_box_follows_the_selected_role_and_changes_it(self):
        self.assertEqual(self.window.tree.rows["Chief"]["values"], ["Chief", "Yes", ""])
        self.select("Chief")
        self.assertTrue(self.window.superuser_var.get())
        self.select("Quality")
        self.assertFalse(self.window.superuser_var.get())
        self.window.superuser_var.set(True)
        self.window._superuser_ticked()
        self.window._save()
        self.assertEqual(self.applied, [(["Quality", "Chief"], ["Quality", "Chief"])])

    def test_the_team_folders_box_follows_the_selected_role(self):
        applied = []
        window = self.gui.roles_dialog.RolesDialog(
            FakeParent(), ["Quality", "Manager"], lambda role: [], folder_roles=["manager"],
            apply=lambda roles, superusers, folders: applied.append(folders) or "")
        self.assertEqual(window.tree.rows["Manager"]["values"], ["Manager", "", "Yes"])
        window.tree.selection_set("Quality")
        window._selected()
        self.assertFalse(window.folders_var.get())
        window.folders_var.set(True)
        window._folders_ticked()
        window._save()
        self.assertEqual(applied, [["Quality", "Manager"]])

    def test_adding_the_standard_roles_ticks_chief(self):
        window = self.gui.roles_dialog.RolesDialog(FakeParent(), ["Quality"], lambda role: [],
                                                   apply=lambda roles, superusers, folders: self.applied.append(superusers) or "")
        window._standard()
        window._save()
        self.assertEqual(self.applied, [["Chief"]])

    def test_nothing_changed_saves_nothing(self):
        self.window._save()
        self.assertEqual(self.applied, [])
