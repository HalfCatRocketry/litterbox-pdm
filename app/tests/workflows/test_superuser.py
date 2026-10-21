"""Tests for superuser roles (a superuser may sign any sign-off, for anyone), Override Reject, and the Workflows
screen's two lists (My Tasks: only requests you sign or asked for; All Workflows: every request). Uses the two-user
vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is a Member with the
Manager role). They need Linux, macOS or WSL."""

import unittest

from tests.support.identities import identity_for
from tests.support.vault_fixture import PART
from tests.support.workflow_fixture import CHIEF, ENGINEER, MANAGER, QUALITY, Fixture
from litterbox.errors import LitterboxError
from litterbox.parts import part_status
from litterbox.records import record_model
from litterbox.team import team_editing
from litterbox.team import team_store
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import workflow_tasks


class Superusers(Fixture, unittest.TestCase):
    def give_roles(self, person_id, roles):
        with self.user("Alex"):
            team_store.edit_directory(self.a, lambda d, who: team_editing.update_person(d, who, person_id, roles=roles),
                                      f"Team: roles of {person_id}")
        for user in ("Bea", "Cy"):
            self.get_latest(user)

    def tasks(self, who, everything=False):
        rows = self.do("Alex", part_status.get_status)
        return workflow_tasks.tasks_from_rows(rows, identity_for(who, team_store.load(self.a)), everything)

    def test_chief_is_a_superuser_role_when_the_team_is_set_up(self):
        directory = team_store.load(self.a)
        self.assertEqual(directory.superuser_roles, [CHIEF])
        self.assertFalse(directory.is_superuser(directory.get("cy")))
        self.give_roles("cy", [MANAGER, CHIEF])
        self.assertTrue(team_store.load(self.a).is_superuser(team_store.load(self.a).get("cy")))

    def test_my_tasks_lists_only_requests_you_sign_or_asked_for(self):
        self.request()
        self.assertEqual(len(self.tasks("bea")), 1)                    # named to sign
        self.assertEqual(len(self.tasks("alex")), 1)                   # asked for it
        self.assertEqual(self.tasks("cy"), [])                         # neither
        (t,) = self.tasks("cy", everything=True)
        self.assertEqual(t.superuser_slots, [])                        # not a superuser
        self.assertFalse(workflow_tasks.can_see_all(identity_for("cy", team_store.load(self.a))))
        self.assertTrue(workflow_tasks.can_see_all(identity_for("alex", team_store.load(self.a))))     # the Owner

    def test_a_superuser_signs_the_ticked_sign_offs_for_whoever_was_named(self):
        self.give_roles("cy", [MANAGER, CHIEF])
        self.request()                                                 # Quality: Bea, Responsible Engineer: Alex
        self.get_latest("Cy")
        self.assertTrue(workflow_tasks.can_see_all(identity_for("cy", team_store.load(self.a))))
        (t,) = self.tasks("cy", everything=True)
        self.assertEqual(t.superuser_slots, [0, 1])
        self.do("Cy", workflow_signoff.sign_as_superuser, [PART], [0], "Bea is away")
        record = self.record()
        (entry,) = record.pending["signoffs"]
        self.assertEqual((entry["slot"], entry["id"], entry["superuser"], entry["for_id"], entry["for"]),
                         (0, "cy", True, "bea", "Bea Jones"))
        event = record.history[-1]
        self.assertEqual((event["roles"], event["superuser"]), ([f"{QUALITY} for Bea Jones"], True))
        (t,) = self.tasks("cy", everything=True)
        self.assertEqual(t.superuser_slots, [1])                       # what is left
        self.do("Cy", workflow_signoff.sign_as_superuser, [PART], [1])  # the same person fills a second sign-off
        record = self.record()
        self.assertEqual((record.status, record.pending), (record_model.STATUS_RELEASED, {}))

    def test_someone_without_a_superuser_role_cant_sign_for_others(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Cy", workflow_signoff.sign_as_superuser, [PART], [0])

    def test_a_superuser_cant_sign_their_own_request_when_the_workflow_forbids_it(self):
        self.give_roles("alex", [ENGINEER, CHIEF])
        self.set_template(rows=((QUALITY,),), requester=False)
        self.request(assign=("bea",))
        (t,) = self.tasks("alex", everything=True)
        self.assertEqual(t.superuser_slots, [])
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_signoff.sign_as_superuser, [PART], [0])
        self.assertEqual(self.record().pending["signoffs"], [])

    def test_a_superuser_can_sign_their_own_request_when_the_workflow_allows_it(self):
        self.give_roles("alex", [ENGINEER, CHIEF])
        self.set_template(rows=((QUALITY,),), requester=True)
        self.request(assign=("bea",))
        self.do("Alex", workflow_signoff.sign_as_superuser, [PART], [0])
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_override_reject_is_for_admins_and_recorded_as_an_override(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Cy", workflow_responses.reject, [PART], "No", override=True)
        self.do("Alex", workflow_responses.reject, [PART], "Wrong material", override=True)
        record = self.record()
        self.assertEqual(record.pending, {})
        self.assertEqual((record.history[-1]["event"], record.history[-1]["override"]),
                         (record_model.EVENT_RELEASE_REJECTED, True))


if __name__ == "__main__":
    unittest.main()
