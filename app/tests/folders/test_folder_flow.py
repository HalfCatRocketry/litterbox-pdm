"""Tests for the Team and project folders in a real vault (folders/folder_store.py, folder_access.py and the check in
team/guarded_push.py): a change goes up and the others see it, one the person may not make is refused and taken
back, two people's changes at once are both kept, and a renamed project keeps its folders. Alex is the Owner, Bea a
member with the Quality role, Cy a member with the Manager role. (Need Linux, macOS or WSL, as git tests do.)"""

import unittest

from tests.support.vault_fixture import PART
from tests.support.workflow_fixture import Fixture

from litterbox.errors import LitterboxError
from litterbox.folders import folder_access
from litterbox.folders import folder_actions
from litterbox.folders import folder_store
from litterbox.folders.folder_actions import Place
from litterbox.team import guarded_push
from litterbox.team import team_editing
from litterbox.team import team_store
from litterbox.vault import project_admin

TEAM, ROVER = Place(folder_access.TEAM), Place(folder_access.PROJECT, "Rover")


class SharedFolders(Fixture, unittest.TestCase):
    def change(self, user, place, ops, message="change"):
        self.do(user, folder_actions.apply_change, place, ops, message, push=guarded_push.push)

    def trees(self, user):
        self.get_latest(user)
        return folder_store.load(self.repo_of(user))

    def test_a_team_folder_goes_up_and_everyone_sees_it(self):
        add = folder_actions.add_folder({}, "", "Front end")
        self.change("Alex", TEAM, [add, {"op": "put", "folder": add["folder"], "items": [str(PART)]}], "Front end")
        team = self.trees("Bea").team
        self.assertEqual((team[add["folder"]].name, team[add["folder"]].items), ("Front end", [str(PART)]))
        self.assertIn("Folders: Front end", self.remote_log())

    def test_a_change_you_may_not_make_is_refused_and_taken_back(self):
        add = folder_actions.add_folder({}, "", "Bea's")
        with self.assertRaises(folder_access.FoldersRefused):
            self.change("Bea", TEAM, [add])
        self.assertEqual(folder_store.load(self.b).team, {})
        self.assertEqual(folder_store.change_files(self.b), [])
        self.do("Alex", team_store.edit_directory, lambda d, who: (
            team_editing.set_roles(d, who, d.roles, folder_roles=["Quality"])), "Team: Quality may change folders")
        self.get_latest("Bea")
        self.change("Bea", TEAM, [add])                                     # her later uploads aren't stuck
        self.assertEqual(self.trees("Alex").team[add["folder"]].name, "Bea's")

    def test_two_peoples_changes_at_once_are_both_kept_and_a_rename_carries_them(self):
        self.do("Alex", project_admin.add_project, "Rover", "9", team={"lead": "alex", "members": ["bea"]})
        self.get_latest("Bea")
        alex = folder_actions.add_folder({}, "", "Wheels")
        bea = folder_actions.add_folder({}, "", "Arm")
        self.change("Bea", ROVER, [bea], "Arm")
        self.change("Alex", ROVER, [alex], "Wheels")                      # without Bea's change: synced on upload
        names = sorted(f.name for f in folder_store.tree_of(self.trees("Bea"), folder_access.PROJECT, "Rover").values())
        self.assertEqual(names, ["Arm", "Wheels"])
        with self.assertRaises(LitterboxError):                           # Cy isn't in Rover
            self.change("Cy", ROVER, [folder_actions.add_folder({}, "", "Mine")])
        self.do("Alex", project_admin.edit_project, "Rover", "Rover II", "9")
        trees = self.trees("Bea")
        self.assertEqual(list(trees.projects), ["Rover II"])
        self.assertEqual(len(trees.projects["Rover II"]), 2)

    def test_an_upload_that_fails_keeps_the_change_for_the_next(self):
        add = folder_actions.add_folder({}, "", "Offline")

        def offline(repo):
            raise LitterboxError("Could not reach the host.")

        with self.assertRaises(LitterboxError):
            self.do("Alex", folder_actions.apply_change, TEAM, [add], "Offline", push=offline)
        self.assertEqual(len(folder_store.change_files(self.a)), 1)       # kept here, committed
        with self.user("Alex"):
            guarded_push.push(self.a)
        self.assertEqual(self.trees("Bea").team[add["folder"]].name, "Offline")


if __name__ == "__main__":
    unittest.main()
