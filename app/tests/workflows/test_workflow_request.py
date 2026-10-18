"""Tests for asking for sign-off (workflow_request). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import DRW, PART, PRT, git
from litterbox.records import record_model
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_request
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import CHIEF, ENGINEER, MANAGER, PART2, PRT2, QUALITY, Fixture
from litterbox.errors import LitterboxError
from litterbox.parts import checkout
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.parts import part_status


class TestRequesting(Fixture, unittest.TestCase):
    def test_a_request_is_recorded_pushed_and_shown(self):
        batch = self.request()
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        record = self.record()
        p = record.pending
        self.assertEqual((p["id"], p["requested_by"], p["requested_by_id"], p["revision"], p["template_name"]),
                         (batch, "Alex Smith", "alex", "A", "T"))
        self.assertEqual([(s["roles"], s["id"]) for s in p["slots"]], [([QUALITY], "bea"), ([ENGINEER], "alex")])
        self.assertEqual(sorted(p["files"]), [DRW, PRT])
        self.assertEqual(p["signoffs"], [])
        self.assertEqual(record.history[-1]["event"], "release_requested")
        self.assertEqual(record.history[-1]["action"], "release")
        self.assertEqual(lfs_locks.get_locks(self.a), {})
        row = next(r for r in self.do("Bea", part_status.get_status) if r.pn == PART)
        self.assertEqual(row.kind, "pending")
        self.assertEqual(row.state, "Release pending 0/2: waiting on Bea Jones, Alex Smith")

    def test_a_batch_covers_every_part_with_one_id(self):
        self.second_part()
        batch = self.request(pns=(PART, PART2))
        a, b = self.record(PART).pending, self.record(PART2).pending
        self.assertEqual((a["id"], b["id"]), (batch, batch))
        self.assertEqual(a["parts"], [str(PART), str(PART2)])
        self.assertEqual(sorted(b["files"]), [PRT2])

    def test_one_part_that_cannot_go_ahead_stops_the_whole_batch(self):
        self.second_part()
        self.set_template()
        with self.user("Bea"):
            checkout.checkout(self.b, PART2)
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART, PART2], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.assertIn(str(PART2), str(ctx.exception))
        self.assertIn("checked out by", str(ctx.exception))
        self.assertEqual(self.record(PART).pending, {})

    def test_the_template_is_copied_into_the_request(self):
        self.request()
        with self.user("Alex"):
            workflow_store.edit_templates(self.a, lambda t, d: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [[QUALITY]], old_name="T"), "x")
        self.assertEqual(len(workflow_store.templates_for(self.a, workflow_templates.RELEASE)["T"].rows), 1)
        self.assertEqual(len(self.record().pending["template"]["signoffs"]), 2)

    def test_the_people_named_must_fit_the_rows(self):
        self.set_template()
        cases = ((["cy", "alex"], "not active with the role"),
                 (["bea"], "Choose a person for every"), (["bea", ""], "Choose a person for sign-off 2"),
                 (["bea", "nobody"], "Choose a person"))
        for assign, text in cases:
            with self.subTest(assign=assign):
                with self.assertRaises(LitterboxError) as ctx:
                    self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", assign)
                self.assertIn(text, str(ctx.exception))
        self.assertEqual(self.record().pending, {})

    def test_one_person_cannot_fill_two_rows_unless_allowed(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["alex", "alex"])
        self.assertIn("doesn't let one person", str(ctx.exception))

    def test_the_same_person_may_fill_two_rows_when_the_template_says_so(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)), same=True)
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["alex", "alex"])
        self.assertEqual([s["id"] for s in self.record().pending["slots"]], ["alex", "alex"])

    def test_the_requester_may_be_barred_from_signing(self):
        self.set_template(requester=False)
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.assertIn("sign your own request", str(ctx.exception))

    def test_optional_extra_sign_offs(self):
        self.set_template()
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"], extras=[(MANAGER, "cy")])
        slots = self.record().pending["slots"]
        self.assertEqual((len(slots), slots[2]["id"], slots[2].get("extra")), (3, "cy", True))
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"], extras=[("Wizard", "cy")])

    def test_or_rows_accept_anyone_with_any_of_the_roles(self):
        self.set_template(rows=((MANAGER, CHIEF),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["cy"])
        self.assertEqual(self.record().pending["slots"][0]["roles"], [MANAGER, CHIEF])
        self.assertIn("Manager or Chief", signoff_slots.slot_text(self.record().pending["slots"][0]))

    def test_reopen_and_void_need_a_reason(self):
        self.do("Alex", lifecycle.release, PART)
        self.set_template(workflow_templates.REOPEN, rows=((MANAGER,),))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART], workflow_templates.REOPEN, "T", ["cy"])
        self.assertIn("reason is required", str(ctx.exception))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.REOPEN, "T", ["cy"], reason="Fix a drawing error")
        self.assertEqual(self.record().pending["reason"], "Fix a drawing error")

    def test_actions_that_cannot_happen_are_refused_up_front(self):
        self.set_template(workflow_templates.REOPEN, rows=((MANAGER,),))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART], workflow_templates.REOPEN, "T", ["cy"], reason="x")
        self.assertIn("status is", str(ctx.exception))

    def test_a_pending_part_cannot_be_checked_out_or_changed(self):
        self.request()
        self.get_latest("Bea")
        for user, func in (("Alex", lambda r: checkout.checkout(r, PART)), ("Bea", lambda r: checkout.checkout(r, PART)),
                           ("Alex", lambda r: workflow_request.request(r, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"]))):
            with self.subTest(user=user):
                with self.user(user), self.assertRaises(LitterboxError):
                    func(self.repo_of(user))

    def test_someone_not_on_the_team_cannot_ask(self):
        self.set_template()
        with self.user("Zed"):
            with self.assertRaises(LitterboxError):
                workflow_request.request(self.b, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])

    def test_the_record_round_trips(self):
        self.request()
        again = record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(self.record())))
        self.assertEqual(again.pending, self.record().pending)


if __name__ == "__main__":
    unittest.main()
