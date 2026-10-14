"""
Tests for workflow.py: templates, requests (single parts and batches), named sign-offs, OR rows, reject,
withdraw, reassign, override and My Tasks. Uses the two-user vault (Alex is the Owner and a Responsible Engineer;
Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support.vault_fixture import DRW, PART, PRT, git

from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.records import record_model
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_responses
from litterbox.workflows import workflow_signoff
from litterbox.workflows import signoff_slots
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_tasks
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import CHIEF, ENGINEER, MANAGER, PART2, PRT2, QUALITY, Fixture
from litterbox.errors import LitterboxError
from litterbox import layout
from litterbox.parts import checkout
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.parts import part_status
from litterbox.git import remote
from litterbox.git import runner


class TestTemplates(Fixture, unittest.TestCase):
    def test_no_file_means_no_workflows(self):
        self.assertEqual(workflow_store.load(self.a), {})
        self.assertEqual(workflow_store.templates_for(self.a, workflow_templates.RELEASE), {})
        self.assertFalse(workflow_store.has_templates(self.a, workflow_templates.RELEASE))

    def test_an_admin_saves_templates_for_everyone(self):
        self.set_template(name="Flight", rows=((ENGINEER,), (ENGINEER,), (MANAGER, CHIEF)), same=True,
                          requester=False)
        for repo in (self.a, self.b):
            t = workflow_store.templates_for(repo, workflow_templates.RELEASE)["Flight"]
            self.assertEqual([r.roles for r in t.rows], [[ENGINEER], [ENGINEER], [MANAGER, CHIEF]])
            self.assertEqual((t.allow_same_person, t.requester_may_sign), (True, False))
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_a_vault_with_a_workflow_asks_for_the_new_version(self):
        from litterbox.vault import compatibility
        from litterbox.vault import config
        from litterbox import version
        self.set_template()
        for repo in (self.a, self.b):
            self.assertEqual(config.load(repo)["min_litterbox_version"], workflow_templates.MIN_VERSION)
        with mock.patch.object(version, "VERSION", "0.2.0"):
            with self.assertRaises(config.ConfigError) as ctx:
                compatibility.check_compatible(self.b)
        self.assertIn("needs Litterbox 0.3.0", str(ctx.exception))

    def test_removing_every_workflow_does_not_lower_the_minimum(self):
        from litterbox.vault import config
        self.set_template()
        with self.user("Alex"):
            workflow_store.edit_templates(self.a, lambda t, d: workflow_editing.remove_template(t, workflow_templates.RELEASE, "T"), "Remove")
        self.assertEqual(workflow_store.load(self.a), {})
        self.assertEqual(config.load(self.a)["min_litterbox_version"], workflow_templates.MIN_VERSION)

    def test_a_failed_save_leaves_things_alone(self):
        real = remote.push_with_retry
        remote.push_with_retry = lambda repo, attempts=3: (_ for _ in ()).throw(LitterboxError("offline"))
        self.addCleanup(setattr, remote, "push_with_retry", real)
        with self.assertRaises(LitterboxError):
            with self.user("Alex"):
                workflow_store.edit_templates(self.a, lambda t, d: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [[QUALITY]]), "x")
        remote.push_with_retry = real
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertFalse((self.a / layout.WORKFLOWS_FILE).exists())
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_a_member_cannot_change_workflows(self):
        with self.assertRaises(LitterboxError) as ctx:
            with self.user("Bea"):
                workflow_store.edit_templates(self.b, lambda t, d: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [[QUALITY]]), "x")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_bad_templates_are_refused_and_leave_nothing_behind(self):
        bad = ((lambda t: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", []), "at least one sign-off"),
               (lambda t: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [["Wizard"]]), "isn't one of this org's roles"),
               (lambda t: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [[QUALITY, "quality"]]), "same role twice"),
               (lambda t: workflow_editing.set_template(t, workflow_templates.RELEASE, "T", [[]]), "at least one role"),
               (lambda t: workflow_editing.set_template(t, workflow_templates.RELEASE, " ", [[QUALITY]]), "needs a name"),
               (lambda t: workflow_editing.set_template(t, "revise", "T", [[QUALITY]]), "can't have a workflow"))
        for change, text in bad:
            with self.subTest(text=text):
                with self.assertRaises(LitterboxError) as ctx:
                    with self.user("Alex"):
                        workflow_store.edit_templates(self.a, lambda t, d, c=change: c(t), "x")
                self.assertIn(text.split()[0], str(ctx.exception))
                self.assertFalse((self.a / layout.WORKFLOWS_FILE).exists())
                self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_duplicate_names_are_refused(self):
        self.set_template()
        with self.assertRaises(LitterboxError) as ctx:
            with self.user("Alex"):
                workflow_store.edit_templates(self.a, lambda t, d: workflow_editing.set_template(t, workflow_templates.RELEASE, "t", [[QUALITY]]), "x")
        self.assertIn("already a Release workflow", str(ctx.exception))

    def test_role_spelling_is_tidied_to_the_orgs(self):
        self.set_template(rows=(("quality", "chief"),))
        self.assertEqual(workflow_store.templates_for(self.a, workflow_templates.RELEASE)["T"].rows[0].roles, [QUALITY, CHIEF])

    def test_renaming_keeps_the_position_and_removing_the_last_drops_the_action(self):
        templates = {}
        for name in ("T1", "T2", "T3"):
            workflow_editing.set_template(templates, workflow_templates.RELEASE, name, [[QUALITY]])
        workflow_editing.set_template(templates, workflow_templates.RELEASE, "Flight", [[ENGINEER]], old_name="T2")
        self.assertEqual(list(templates[workflow_templates.RELEASE]), ["T1", "Flight", "T3"])
        for name in ("T1", "Flight", "T3"):
            workflow_editing.remove_template(templates, workflow_templates.RELEASE, name)
        self.assertEqual(templates, {})

    def test_standard_workflows_need_their_roles(self):
        directory = team_store.load(self.a)
        directory.roles = [ENGINEER, MANAGER]
        templates = {}
        missing = workflow_editing.add_standard(templates, directory)
        self.assertEqual(missing, ["Manufacturing", "Analysis", CHIEF])
        self.assertEqual(list(templates[workflow_templates.RELEASE]), ["T1", "T2", "T3"])
        self.assertEqual(set(templates), set(workflow_templates.ACTIONS))
        again = workflow_editing.add_standard(templates, directory)
        self.assertEqual(len(templates[workflow_templates.RELEASE]), 3)
        self.assertEqual(again, missing)

    def test_the_old_format_gets_a_clear_message(self):
        (self.a / ".litterbox").mkdir(exist_ok=True)
        (self.a / layout.WORKFLOWS_FILE).write_text("workflows:\n  release:\n    signoffs:\n    - role: Quality\n")
        with self.assertRaises(LitterboxError) as ctx:
            workflow_store.load(self.a)
        self.assertIn("Litterbox 0.2", str(ctx.exception))

    def test_people_for_a_row_include_everyone_with_any_of_its_roles(self):
        directory = team_store.load(self.a)
        self.assertEqual([p.id for p in workflow_editing.eligible(directory, [MANAGER, QUALITY])], ["bea", "cy"])
        directory.people[1].active = False
        self.assertEqual([p.id for p in workflow_editing.eligible(directory, [MANAGER, QUALITY])], ["cy"])

    def test_warnings(self):
        directory = team_store.load(self.a)
        t = workflow_templates.Template(workflow_templates.RELEASE, "T", [workflow_templates.Row(["Manufacturing"]), workflow_templates.Row([QUALITY])])
        self.assertEqual(len(workflow_editing.role_warnings(t, directory)), 1)
        self.assertIn("nobody active", workflow_editing.role_warnings(t, directory)[0])
        t = workflow_templates.Template(workflow_templates.RELEASE, "T", [workflow_templates.Row([QUALITY]), workflow_templates.Row([QUALITY])])
        self.assertIn("enough different people", workflow_editing.role_warnings(t, directory)[0])
        t.allow_same_person = True
        self.assertEqual(workflow_editing.role_warnings(t, directory), [])
        t = workflow_templates.Template(workflow_templates.RELEASE, "T", [workflow_templates.Row([QUALITY, MANAGER]), workflow_templates.Row([QUALITY])])
        self.assertEqual(workflow_editing.role_warnings(t, directory), [])

    def test_a_vault_without_a_team_cannot_have_workflows(self):
        with mock.patch.object(team_permissions, "require", return_value=team_identity.Identity(team_identity.LEGACY)):
            with self.assertRaises(LitterboxError) as ctx:
                workflow_store.edit_templates(self.a, lambda t, d: None, "x")
        self.assertIn("Set up the team", str(ctx.exception))


class TestWithoutAWorkflowThingsWorkAsBefore(Fixture, unittest.TestCase):
    def test_plain_release(self):
        self.do("Alex", lifecycle.release, PART)
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_direct_actions_are_refused_once_there_are_templates(self):
        for action, call in ((workflow_templates.RELEASE, lambda r: lifecycle.release(r, PART)),
                             (workflow_templates.MAKE_COTS, lambda r: lifecycle.make_cots(r, PART)),
                             (workflow_templates.VOID, lambda r: lifecycle.void(r, PART, "no")),
                             (workflow_templates.REOPEN, lambda r: lifecycle.reopen(r, PART, "no"))):
            with self.subTest(action=action):
                self.set_template(action)
                with self.assertRaises(LitterboxError) as ctx:
                    self.do("Alex", call)
                self.assertIn("needs sign-offs", str(ctx.exception))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)

    def test_requesting_without_a_template_says_so(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.assertIn("no Release workflow called 'T'", str(ctx.exception))


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


class TestSigning(Fixture, unittest.TestCase):
    def test_the_last_signature_releases(self):
        self.request()
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)
        self.get_latest("Bea")
        r = self.do("Bea", workflow_signoff.sign_off, [PART], "Looks good")
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_RELEASED, "A", {}))
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_the_trail_is_kept_in_approvals(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.get_latest("Bea")
        self.do("Bea", workflow_signoff.sign_off, [PART], "Looks good")
        entry = self.record().approvals[-1]
        self.assertEqual((entry["action"], entry["template_name"], entry["requested_by"]), ("release", "T", "Alex Smith"))
        self.assertEqual([(e["id"], e["slot"]) for e in entry["signoffs"]], [("alex", 1), ("bea", 0)])
        self.assertEqual(entry["signoffs"][1]["comment"], "Looks good")
        self.assertEqual(sorted(entry["files"]), [DRW, PRT])
        released = [e for e in self.record().history if e["event"] == "released"][-1]
        self.assertEqual(released["signoffs"], ["Alex Smith", "Bea Jones"])

    def test_a_batch_is_uploaded_once_per_step_not_once_per_part(self):
        self.second_part()
        self.set_template()
        seen, real = [], runner.run

        def recording(command, repo, quiet=False):
            seen.append(" ".join(command))
            return real(command, repo, quiet)

        replace_run = mock.patch.object(runner, "run", recording)
        with replace_run:
            self.request(pns=(PART, PART2))                       # one upload for the request
            requested = sum(1 for c in seen if c == "git push")
            self.do("Alex", workflow_signoff.sign_off, [PART, PART2])           # one for Alex's signatures
            self.get_latest("Bea")
            self.do("Bea", workflow_signoff.sign_off, [PART, PART2])            # one for hers, one for the release itself
        self.assertEqual(requested, 1)
        self.assertEqual(sum(1 for c in seen if c == "git push"), 4)
        self.assertEqual(sum(1 for c in seen if c.startswith("git commit")), 4)      # one commit per step, not per part
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_a_batch_is_signed_once_for_every_part(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.sign_off, [PART, PART2])
        self.get_latest("Bea")
        r = self.do("Bea", workflow_signoff.sign_off, [PART, PART2])
        self.assertEqual(sorted(map(str, r.completed)), sorted(map(str, [PART, PART2])))
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_signing_again_or_when_not_named_does_nothing(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertIn("nothing for you to sign", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Cy", workflow_signoff.sign_off, [PART])

    def test_one_person_named_twice_signs_both_at_once(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)), same=True)
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["alex", "alex"])
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])

    def test_a_failed_completion_keeps_the_signature_and_can_be_finished_later(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        self.get_latest("Bea")
        real = workflow_signoff._finish_many
        workflow_signoff._finish_many = lambda repo, pns, **k: (_ for _ in ()).throw(LitterboxError("offline"))
        try:
            r = self.do("Bea", workflow_signoff.sign_off, [PART])
        finally:
            workflow_signoff._finish_many = real
        self.assertEqual((r.signed, r.completed, r.errors), ([PART], [], {PART: "offline"}))
        self.get_latest("Alex")
        row = next(x for x in self.do("Alex", part_status.get_status) if x.pn == PART)
        self.assertEqual((row.kind, row.state), ("pending", "Release approved - ready to complete"))
        self.assertEqual(self.do("Alex", workflow_signoff.complete, PART), [DRW, PRT])
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_completing_before_everyone_signed_is_refused(self):
        self.request()
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_signoff.complete, PART)
        self.assertIn("Quality (Bea Jones)", str(ctx.exception))

    def test_a_file_changed_since_the_request_stops_signing(self):
        self.request()
        self.get_latest("Bea")
        (self.b / PRT).chmod(0o644)
        (self.b / PRT).write_bytes(b"someone sneaked a change in")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_signoff.sign_off, [PART])
        self.assertIn("different from the file", str(ctx.exception))
        git(self.b, "checkout", "--", str(PRT))

    def test_reopen_completes_automatically(self):
        self.do("Alex", lifecycle.release, PART)
        self.set_template(workflow_templates.REOPEN, rows=((MANAGER, CHIEF),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.REOPEN, "T", ["cy"], reason="Drawing error")
        r = self.do("Cy", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_IN_WORK, "", {}))
        self.assertEqual([e for e in record.history if e["event"] == "reopened"][-1]["reason"], "Drawing error")
        self.assertEqual(record.approvals[-1]["reason"], "Drawing error")

    def test_void_completes_automatically(self):
        self.set_template(workflow_templates.VOID, rows=((MANAGER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.VOID, "T", ["cy"], reason="Not needed")
        r = self.do("Cy", workflow_signoff.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        self.assertEqual(self.record().status, record_model.STATUS_VOID)

    def test_make_cots_waits_for_someone_to_complete_it(self):
        self.set_template(workflow_templates.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.MAKE_COTS, "T", ["alex"])
        r = self.do("Alex", workflow_signoff.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertTrue(signoff_slots.is_complete(self.record().pending))
        self.assertFalse(self.record().cots)
        self.do("Alex", workflow_signoff.complete, PART)
        self.assertTrue(self.record().cots)
        self.assertEqual(self.record().pending, {})


class TestRejectingWithdrawingReassigning(Fixture, unittest.TestCase):
    def test_rejecting_sends_the_whole_batch_back(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.sign_off, [PART, PART2])
        self.get_latest("Bea")
        self.do("Bea", workflow_responses.reject, [PART, PART2], "Wrong tolerance")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.pending, record.status), ({}, record_model.STATUS_IN_WORK))
            last = record.history[-1]
            self.assertEqual((last["event"], last["reason"], last["signed"]), ("release_rejected", "Wrong tolerance",
                                                                               ["Alex Smith"]))

    def test_a_reason_is_required_to_reject(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_responses.reject, [PART], "  ")

    def test_only_named_signers_or_admins_reject(self):
        self.request()
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Cy", workflow_responses.reject, [PART], "no")
        self.assertIn("named to sign", str(ctx.exception))
        self.assertTrue(self.record().pending)

    def test_the_requester_can_withdraw_but_other_members_cannot(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.withdraw, [PART])
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", workflow_responses.withdraw, [PART], "Changed my mind")
        self.assertEqual(self.record().pending, {})
        self.assertEqual(self.record().history[-1]["event"], "release_withdrawn")

    def test_after_a_withdrawal_a_new_request_can_be_made(self):
        self.request()
        self.do("Alex", workflow_responses.withdraw, [PART])
        self.request()
        self.assertTrue(self.record().pending)

    def test_the_requester_can_change_who_signs(self):
        self.set_template(rows=((QUALITY, MANAGER), (ENGINEER,)))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_responses.reassign, [PART], 0, "cy")
        slot = self.record().pending["slots"][0]
        self.assertEqual((slot["id"], slot["name"]), ("cy", "Cy Day"))
        self.assertEqual(self.record().history[-1]["event"], "workflow_reassigned")

    def test_reassigning_respects_the_rules(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_responses.reassign, [PART], 0, "cy")                # Cy has no Quality role
        self.assertIn("not active with the role", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_responses.reassign, [PART], 0, "bea")
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", workflow_signoff.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", workflow_responses.reassign, [PART], 1, "alex")
        self.assertIn("already been given", str(ctx.exception))


class TestOverride(Fixture, unittest.TestCase):
    def test_a_member_cannot_override(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", workflow_signoff.override, [PART], "urgent")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_a_reason_is_required(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", workflow_signoff.override, [PART], " ")

    def test_an_admin_releases_a_batch_without_the_sign_offs(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", workflow_signoff.override, [PART, PART2], "Customer deadline")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.status, record.pending), (record_model.STATUS_RELEASED, {}))
            released = [e for e in record.history if e["event"] == "released"][-1]
            self.assertTrue(released["override"])
            self.assertEqual(record.approvals[-1]["override"]["reason"], "Customer deadline")
            self.assertEqual(len(record.approvals[-1]["override"]["missing"]), 2)

    def test_an_admin_can_act_with_no_request_at_all(self):
        self.set_template()
        self.do("Alex", workflow_signoff.override, [PART], "Urgent", action=workflow_templates.RELEASE)
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_an_override_can_void_with_its_reason(self):
        self.set_template(workflow_templates.VOID, rows=((MANAGER,),))
        self.do("Alex", workflow_signoff.override, [PART], "Duplicate part", action=workflow_templates.VOID)
        self.assertEqual(self.record().status, record_model.STATUS_VOID)


def identity_for(person_id, directory, access=team_model.MEMBER):
    person = directory.get(person_id)
    return SimpleNamespace(state=team_identity.OK, person=person, directory=directory)


class TestTasks(Fixture, unittest.TestCase):
    def rows(self, user="Alex"):
        return self.do(user, part_status.get_status)

    def tasks(self, who, user="Alex"):
        return workflow_tasks.tasks_from_rows(self.rows(user), identity_for(who, team_store.load(self.a)))

    def test_nothing_pending_means_no_tasks(self):
        self.assertEqual(self.tasks("alex"), [])

    def test_a_named_signer_can_sign_and_reject(self):
        self.request()
        (t,) = self.tasks("bea", "Bea")
        self.assertEqual((t.can_sign, t.can_reject, t.can_withdraw, t.can_override, t.can_reassign),
                         (True, True, False, False, False))
        self.assertEqual(t.label, str(PART))
        self.assertEqual([s["name"] for s in t.slots], ["Bea Jones", "Alex Smith"])

    def test_someone_not_named_only_looks(self):
        self.request()
        (t,) = self.tasks("cy")
        self.assertEqual((t.can_sign, t.can_reject, t.can_complete), (False, False, False))
        self.assertIn("not one of the people named", t.why_not_sign)

    def test_the_requester_can_withdraw_and_reassign_and_an_admin_can_override(self):
        self.request()
        (t,) = self.tasks("alex")
        self.assertEqual((t.can_withdraw, t.can_override, t.can_reassign, t.mine), (True, True, True, True))

    def test_a_batch_is_one_task_and_done_means_signed_on_every_part(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        (t,) = self.tasks("alex")
        self.assertEqual((len(t.parts), t.label), (2, f"{PART} +1 more"))
        self.do("Alex", workflow_signoff.sign_off, [PART])                           # only one of the two parts
        (t,) = self.tasks("alex")
        self.assertTrue(t.can_sign)                                    # still something to sign on the other
        self.assertFalse(t.slots[1]["done"])

    def test_an_approved_request_waits_on_its_requester_to_complete(self):
        self.set_template(workflow_templates.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", workflow_request.request, [PART], workflow_templates.MAKE_COTS, "T", ["alex"])
        self.do("Alex", workflow_signoff.sign_off, [PART])
        (t,) = self.tasks("alex")
        self.assertEqual((t.ready, t.can_complete, workflow_tasks.count_for_me([t])), (True, True, 1))

    def test_nobody_can_act_without_a_team_identity(self):
        self.request()
        ident = SimpleNamespace(state=team_identity.NOT_LISTED, person=None, directory=None)
        (t,) = workflow_tasks.tasks_from_rows(self.rows(), ident)
        self.assertFalse(any((t.can_sign, t.can_reject, t.can_complete, t.can_withdraw, t.can_override)))

    def test_things_waiting_on_me_come_first(self):
        self.second_part()
        self.request(pns=(PART,), assign=("cy", "alex")) if False else None
        self.set_template()
        self.do("Alex", workflow_request.request, [PART], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_request.request, [PART2], workflow_templates.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", workflow_signoff.sign_off, [PART2])
        tasks = self.tasks("alex")
        self.assertEqual([str(t.pns[0]) for t in tasks], [str(PART), str(PART2)])


class TestDescribing(unittest.TestCase):
    def pending(self, signed=()):
        return {"action": "release", "slots": [{"roles": ["Quality"], "id": "bea", "name": "Bea"},
                                               {"roles": ["Manager", "Chief"], "id": "cy", "name": "Cy"}],
                "signoffs": [{"slot": i} for i in signed]}

    def test_progress_text(self):
        self.assertEqual(signoff_slots.describe_pending(self.pending()), "Release pending 0/2: waiting on Bea, Cy")
        self.assertEqual(signoff_slots.describe_pending(self.pending([0])), "Release pending 1/2: waiting on Cy")
        self.assertEqual(signoff_slots.describe_pending(self.pending([0, 1])), "Release approved - ready to complete")
        self.assertEqual(signoff_slots.waiting_on(self.pending([0])), ["Manager or Chief (Cy)"])

    def test_open_slots_and_may_sign(self):
        p = self.pending([0])
        person = SimpleNamespace(id="cy")
        self.assertEqual(signoff_slots.open_slots(p, "cy"), [1])
        self.assertEqual(signoff_slots.open_slots(p, "bea"), [])
        self.assertEqual(signoff_slots.may_sign(p, person), (True, ""))
        self.assertIn("already signed", signoff_slots.may_sign(p, SimpleNamespace(id="bea"))[1])
        self.assertIn("not one of the people", signoff_slots.may_sign(p, SimpleNamespace(id="zed"))[1])


if __name__ == "__main__":
    unittest.main()
