"""Tests for incoming_requests: My Tasks shows the server's requests at a refresh, before Get Latest. Uses the
two-user vault (Alex asks, Bea signs). They need Linux, macOS or WSL."""

import unittest
from unittest import mock

from tests.support.identities import identity_for
from tests.support.vault_fixture import PART, git
from tests.support.workflow_fixture import PART2, PRT2, Fixture

from litterbox.git import read_only
from litterbox.git import remote
from litterbox.git import sparse
from litterbox.parts import part_status
from litterbox.records import record_store
from litterbox.team import team_store
from litterbox.workflows import incoming_requests
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates

RELEASE = workflow_templates.RELEASE


class TestIncomingRequests(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.set_template()

    def ask(self, pns=(PART,)):
        """Alex asks Bea to sign; Bea's copy doesn't get it."""
        return self.do("Alex", workflow_request.request, list(pns), RELEASE, "T", ["bea", "alex"])

    def bea_tasks(self):
        """Bea's My Tasks as a refresh works it out: fetch, then the server's requests on top of her rows."""
        with self.user("Bea"):
            behind = remote.commits_behind(self.b)
            incoming = incoming_requests.read(self.b) if behind else {}
            rows = part_status.get_status(self.b)
        return workflow_tasks.tasks_from_rows(incoming_requests.apply(rows, incoming),
                                              identity_for("bea", team_store.load(self.b)))

    def test_a_request_shows_before_get_latest_and_is_marked_incoming(self):
        self.ask()
        self.assertFalse(record_store.load(self.b, PART).pending)        # her copy hasn't got it
        (task,) = self.bea_tasks()
        self.assertEqual((task.pns, task.can_sign, task.incoming), ([PART], True, True))
        self.get_latest("Bea")
        (task,) = self.bea_tasks()
        self.assertFalse(task.incoming)                                  # now it is in her copy

    def test_a_request_withdrawn_on_the_server_goes(self):
        self.ask()
        self.get_latest("Bea")
        self.do("Alex", workflow_responses.withdraw, [PART])
        self.assertTrue(record_store.load(self.b, PART).pending)         # her copy still has it
        self.assertEqual(self.bea_tasks(), [])

    def test_a_part_new_on_the_server_gets_a_row_for_the_task(self):
        (self.a / PRT2).write_bytes(b"part two")
        record_store.create_record(self.a, PART2, "Second", "Alex")
        git(self.a, "add", ".")
        git(self.a, "commit", "-m", "Second part")
        git(self.a, "push")
        with self.user("Alex"):
            read_only.enforce_read_only(self.a)
        self.ask(pns=(PART2,))
        self.assertFalse(record_store.exists(self.b, PART2))
        (task,) = self.bea_tasks()
        self.assertEqual((task.pns, task.parts[0][1], task.incoming), ([PART2], "Second", True))

    def test_a_hidden_projects_records_stay_out(self):
        self.ask()
        with mock.patch.object(sparse, "excluded", return_value=[f"/PN-logs/{str(PART)[:6]}*"]):
            self.assertEqual(self.bea_tasks(), [])

    def test_nothing_is_read_when_the_copy_is_up_to_date(self):
        self.ask()
        self.get_latest("Bea")
        with self.user("Bea"):
            self.assertEqual(incoming_requests.read(self.b), {})


class TestApply(unittest.TestCase):
    def test_no_incoming_leaves_the_rows_alone(self):
        rows = [part_status.PartStatus(PART, "Bracket", "in_work", "Available", "ok")]
        self.assertEqual(incoming_requests.apply(rows, {}), rows)

    def test_a_record_with_no_request_now_clears_the_rows_request(self):
        row = part_status.PartStatus(PART, "Bracket", "in_work", "", "pending", pending={"slots": []})
        (after,) = incoming_requests.apply([row], {str(PART): None})
        self.assertEqual((after.pending, after.draft, after.incoming), ({}, {}, True))


if __name__ == "__main__":
    unittest.main()
