"""Tests for ECOs in workflows (workflow_ecos, and the ECO steps in workflow_request/signoff/responses). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role). They need Linux, macOS or WSL."""

import os
import unittest
from unittest import mock
from tests.support.vault_fixture import PART, git
from litterbox.change_orders import eco_lifecycle
from litterbox.change_orders import eco_model
from litterbox.change_orders import eco_store
from litterbox.errors import LitterboxError
from litterbox.git import remote
from litterbox.records import record_model
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from tests.support.workflow_fixture import PART2, Fixture

ECO = {"name": "Thicker bracket", "description": "Wall from 2 mm to 3 mm"}


class TestEcos(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.set_template(eco=True)

    def last_commit_files(self, repo):
        return git(repo, "show", "--name-only", "--format=", "HEAD").split()

    def test_starting_writes_the_eco_in_the_same_commit(self):
        self.second_part()
        self.request(pns=(PART, PART2), eco=ECO)
        self.assertIn("ECO/ECO-0001.yaml", self.last_commit_files(self.b))
        eco = eco_store.load(self.b, "ECO-0001")
        self.assertEqual((eco.name, eco.description, eco.status, eco.template_name),
                         ("Thicker bracket", "Wall from 2 mm to 3 mm", eco_model.OPEN, "T"))
        self.assertEqual([p["pn"] for p in eco.parts], [str(PART), str(PART2)])
        self.assertFalse(os.access(self.b / "ECO" / "ECO-0001.yaml", os.W_OK))     # read-only in every copy
        record = self.record()
        self.assertEqual(record.pending["eco"], "ECO-0001")
        self.assertEqual(eco.request_id, record.pending["id"])
        self.assertEqual(record.history[-1]["eco"], "ECO-0001")

    def test_a_name_is_required_and_nothing_changes_without_it(self):
        head = git(self.a, "rev-parse", "HEAD")
        with self.assertRaises(LitterboxError) as ctx:
            self.request(eco={"name": "  ", "description": "x"})
        self.assertIn("needs a name", str(ctx.exception))
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), head)
        self.assertFalse((self.a / "ECO").exists())

    def test_a_template_without_the_box_makes_no_eco(self):
        self.set_template(name="Plain")
        self.request(name="Plain", eco=ECO)
        self.assertFalse((self.a / "ECO").exists())
        self.assertNotIn("eco", self.record().pending)

    def test_numbers_go_up(self):
        self.second_part()
        self.request(eco=ECO)
        self.request(pns=(PART2,), eco={"name": "Second"})
        self.assertEqual(eco_store.numbers(self.b), ["ECO-0001", "ECO-0002"])
        self.assertEqual(self.record(PART2).pending["eco"], "ECO-0002")

    def test_a_number_taken_meanwhile_moves_to_the_next(self):
        with self.user("Bea"):                         # Bea's ECO-0001 reaches the vault after Alex's last pull
            eco_lifecycle.open_eco(self.b, "Bea's", "", "release", "T", "zzz", [], "Bea Jones")
            git(self.b, "add", ".")
            git(self.b, "commit", "-m", "ECO")
            git(self.b, "push")
        real_pull, calls = remote.pull, []

        def stale_pull(repo, *args, **kwargs):           # the first pull misses Bea's push
            calls.append(repo)
            if len(calls) > 1:
                return real_pull(repo, *args, **kwargs)
        with mock.patch.object(remote, "pull", stale_pull):
            self.request(eco=ECO)
        self.assertEqual(self.record().pending["eco"], "ECO-0002")
        self.assertEqual(eco_store.load(self.a, "ECO-0001").name, "Bea's")
        self.assertEqual(eco_store.load(self.a, "ECO-0002").name, "Thicker bracket")

    def test_the_last_sign_off_releases_the_eco(self):
        self.second_part()
        self.request(pns=(PART, PART2), eco=ECO)
        self.do("Alex", workflow_signoff.sign_off, [PART, PART2])
        self.get_latest("Bea")
        self.assertEqual(eco_store.load(self.b, "ECO-0001").status, eco_model.OPEN)
        self.do("Bea", workflow_signoff.sign_off, [PART, PART2], "Good")
        self.assertIn("ECO/ECO-0001.yaml", self.last_commit_files(self.b))
        eco = eco_store.load(self.b, "ECO-0001")
        self.assertEqual(eco.status, eco_model.RELEASED)
        self.assertEqual(sorted(s["id"] for s in eco.signoffs), ["alex", "bea"])
        self.assertEqual(eco.history[-1]["event"], "released")
        self.assertEqual(self.record().approvals[-1]["eco"], "ECO-0001")
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_an_override_releases_the_eco_with_its_reason(self):
        self.request(eco=ECO)
        self.do("Alex", workflow_signoff.override, [PART], "Customer deadline")
        eco = eco_store.load(self.a, "ECO-0001")
        self.assertEqual((eco.status, eco.history[-1].get("comment")), (eco_model.RELEASED, "Customer deadline"))

    def test_rejecting_and_withdrawing_close_the_eco(self):
        self.request(eco=ECO)
        self.get_latest("Bea")
        self.do("Bea", workflow_responses.reject, [PART], "Too thin")
        eco = eco_store.load(self.b, "ECO-0001")
        self.assertEqual((eco.status, eco.history[-1]["comment"]), (eco_model.REJECTED, "Too thin"))
        self.get_latest("Alex")
        self.request(eco={"name": "Try again"})
        self.do("Alex", workflow_responses.withdraw, [PART], "Not needed")
        self.assertEqual(eco_store.load(self.a, "ECO-0002").status, eco_model.WITHDRAWN)
        self.assertEqual(eco_store.load(self.a, "ECO-0001").status, eco_model.REJECTED)

    def test_a_closed_eco_stops_the_change_and_nothing_is_kept(self):
        self.request(eco=ECO)
        eco = eco_store.load(self.a, "ECO-0001")       # closed by hand behind Litterbox's back
        eco.status = eco_model.WITHDRAWN
        eco_store.save(self.a, eco)
        git(self.a, "commit", "-am", "closed")
        git(self.a, "push")
        head = git(self.a, "rev-parse", "HEAD")
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_responses.withdraw, [PART])
        self.assertEqual(git(self.a, "rev-parse", "HEAD"), head)
        self.assertTrue(self.record().pending)
        self.assertEqual(git(self.a, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
