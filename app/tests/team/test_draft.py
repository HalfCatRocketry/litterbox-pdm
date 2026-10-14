"""Tests for team_draft.py: team edits collected first and saved in one go. Need Linux, macOS or WSL."""

import unittest
from unittest import mock

from tests.support.vault_fixture import SKIP_ON_WINDOWS, TwoUserVault, git

from litterbox.team import team_editing
from litterbox.team import team_model
from litterbox.team import team_setup
from litterbox.team import team_store
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates
from litterbox.team.draft import TeamDraft
from litterbox.errors import LitterboxError, NothingToSaveError
from litterbox import diagnostics

ENGINEER, QUALITY = "Responsible Engineer", "Quality"


@SKIP_ON_WINDOWS
class DraftFixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        quiet = mock.patch.object(diagnostics, "LOG", lambda *_: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        with self.user("Alex"):
            team_setup.setup_team(self.a, "Alex Smith", "alex@x.com")
            team_store.edit_directory(self.a, lambda d, who: team_editing.set_roles(d, who, [ENGINEER, QUALITY]), "roles")

    def draft(self):
        with self.user("Alex"):
            return TeamDraft(team_store.load(self.a), workflow_store.load(self.a), "alex")

    def commits(self):
        return int(git(self.a, "rev-list", "--count", "HEAD").strip())


class TestStaging(DraftFixture, unittest.TestCase):
    def test_nothing_staged_is_clean(self):
        d = self.draft()
        self.assertFalse(d.dirty)
        self.assertEqual(d.summary(), "")

    def test_a_staged_change_shows_in_the_draft_but_not_in_the_vault(self):
        d = self.draft()
        d.stage_people("Add Bea", lambda dr, who: team_editing.add_person(dr, who, "bea", "Bea Jones", "", ["Bea"]))
        self.assertIsNotNone(d.directory.get("bea"))
        self.assertTrue(d.dirty)
        self.assertEqual(d.summary(), "1 unsaved change: Add Bea")
        with self.user("Alex"):
            self.assertIsNone(team_store.load(self.a).get("bea"))

    def test_a_mistake_is_reported_at_once_and_not_kept(self):
        d = self.draft()
        with self.assertRaises(LitterboxError):
            d.stage_people("Bad", lambda dr, who: team_editing.add_person(dr, who, "alex", "Again"))
        self.assertFalse(d.dirty)
        self.assertEqual(len(d.directory.people), 1)

    def test_several_changes_make_one_commit(self):
        d = self.draft()
        before = self.commits()
        d.stage_people("Add Bea", lambda dr, who: team_editing.add_person(dr, who, "bea", "Bea Jones", "", ["Bea"],
                                                                    team_model.MEMBER, [QUALITY]))
        d.stage_people("Alex roles", lambda dr, who: team_editing.update_person(dr, who, "alex", roles=[ENGINEER]))
        with self.user("Alex"):
            saved = d.save(self.a)
        self.assertEqual(saved, ["Add Bea", "Alex roles"])
        self.assertEqual(self.commits(), before + 1)
        self.assertFalse(d.dirty)
        with self.user("Alex"):
            self.assertEqual(team_store.load(self.a).get("bea").roles, [QUALITY])

    def test_people_and_workflow_make_two_commits(self):
        d = self.draft()
        before = self.commits()
        d.stage_people("Add Bea", lambda dr, who: team_editing.add_person(dr, who, "bea", "Bea Jones", "", ["Bea"],
                                                                    team_model.MEMBER, [QUALITY]))
        d.stage_workflow("Release workflow", lambda t, dr: workflow_editing.set_template(t, workflow_templates.RELEASE, "T1", [[QUALITY]]))
        with self.user("Alex"):
            d.save(self.a)
        self.assertEqual(self.commits(), before + 2)
        with self.user("Alex"):
            self.assertIn("T1", workflow_store.load(self.a)[workflow_templates.RELEASE])

    def test_a_workflow_cannot_use_a_role_that_is_not_there(self):
        d = self.draft()
        with self.assertRaises(LitterboxError):
            d.stage_workflow("Bad", lambda t, dr: workflow_editing.set_template(t, workflow_templates.RELEASE, "T1", [["Nobody"]]))
        self.assertFalse(d.dirty)

    def test_changes_saved_by_others_meanwhile_are_kept(self):
        d = self.draft()
        d.stage_people("Add Bea", lambda dr, who: team_editing.add_person(dr, who, "bea", "Bea Jones", "", ["Bea"]))
        with self.user("Alex"):
            team_store.edit_directory(self.a, lambda dr, who: team_editing.add_person(dr, who, "cy", "Cy Day"), "Team: Cy")
        with self.user("Alex"):
            d.save(self.a)
            ids = sorted(p.id for p in team_store.load(self.a).people)
        self.assertEqual(ids, ["alex", "bea", "cy"])

    def test_staged_changes_that_cancel_out_say_there_is_nothing_to_save(self):
        d = self.draft()
        d.stage_people("Rename", lambda dr, who: team_editing.update_person(dr, who, "alex", name="Zed"))
        d.stage_people("Rename back", lambda dr, who: team_editing.update_person(dr, who, "alex", name="Alex Smith"))
        with self.user("Alex"), self.assertRaises(NothingToSaveError):
            d.save(self.a)
        self.assertFalse(d.dirty)

    def test_handing_over_ownership_is_a_staged_change_too(self):
        d = self.draft()
        d.stage_people("Add Bea", lambda dr, who: team_editing.add_person(dr, who, "bea", "Bea Jones", "", ["Bea"]))
        d.stage_people("Owner to Bea", lambda dr, who: team_editing.transfer_owner(dr, who, "bea"), needs_owner=True)
        self.assertTrue(d.needs_owner)
        with self.user("Alex"):
            d.save(self.a)
            self.assertEqual(team_store.load(self.a).owner().id, "bea")
        self.assertFalse(d.needs_owner)


if __name__ == "__main__":
    unittest.main()
