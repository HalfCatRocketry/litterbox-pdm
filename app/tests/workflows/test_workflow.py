"""
Tests for workflow.py: templates, requests (single parts and batches), named sign-offs, OR rows, reject,
withdraw, reassign, override and My Tasks. Uses the two-user vault (Alex is the Owner and a Responsible Engineer;
Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support.vault_fixture import DRW, PART, PRT, git

from litterbox.team import people
from litterbox.records import record_model
from litterbox.workflows import workflow as wf
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
        self.assertEqual(wf.load(self.a), {})
        self.assertEqual(wf.templates_for(self.a, wf.RELEASE), {})
        self.assertFalse(wf.has_templates(self.a, wf.RELEASE))

    def test_an_admin_saves_templates_for_everyone(self):
        self.set_template(name="Flight", rows=((ENGINEER,), (ENGINEER,), (MANAGER, CHIEF)), same=True,
                          requester=False)
        for repo in (self.a, self.b):
            t = wf.templates_for(repo, wf.RELEASE)["Flight"]
            self.assertEqual([r.roles for r in t.rows], [[ENGINEER], [ENGINEER], [MANAGER, CHIEF]])
            self.assertEqual((t.allow_same_person, t.requester_may_sign), (True, False))
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_a_vault_with_a_workflow_asks_for_the_new_version(self):
        from litterbox.vault import config
        from litterbox import version
        self.set_template()
        for repo in (self.a, self.b):
            self.assertEqual(config.load(repo)["min_litterbox_version"], wf.MIN_VERSION)
        with mock.patch.object(version, "VERSION", "0.2.0"):
            with self.assertRaises(config.ConfigError) as ctx:
                config.check_compatible(self.b)
        self.assertIn("needs Litterbox 0.3.0", str(ctx.exception))

    def test_removing_every_workflow_does_not_lower_the_minimum(self):
        from litterbox.vault import config
        self.set_template()
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.remove_template(t, wf.RELEASE, "T"), "Remove")
        self.assertEqual(wf.load(self.a), {})
        self.assertEqual(config.load(self.a)["min_litterbox_version"], wf.MIN_VERSION)

    def test_a_failed_save_leaves_things_alone(self):
        real = remote.push_with_retry
        remote.push_with_retry = lambda repo, attempts=3: (_ for _ in ()).throw(LitterboxError("offline"))
        self.addCleanup(setattr, remote, "push_with_retry", real)
        with self.assertRaises(LitterboxError):
            with self.user("Alex"):
                wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, "T", [[QUALITY]]), "x")
        remote.push_with_retry = real
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.assertFalse((self.a / layout.WORKFLOWS_FILE).exists())
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_a_member_cannot_change_workflows(self):
        with self.assertRaises(LitterboxError) as ctx:
            with self.user("Bea"):
                wf.edit_templates(self.b, lambda t, d: wf.set_template(t, wf.RELEASE, "T", [[QUALITY]]), "x")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_bad_templates_are_refused_and_leave_nothing_behind(self):
        bad = ((lambda t: wf.set_template(t, wf.RELEASE, "T", []), "at least one sign-off"),
               (lambda t: wf.set_template(t, wf.RELEASE, "T", [["Wizard"]]), "isn't one of this org's roles"),
               (lambda t: wf.set_template(t, wf.RELEASE, "T", [[QUALITY, "quality"]]), "same role twice"),
               (lambda t: wf.set_template(t, wf.RELEASE, "T", [[]]), "at least one role"),
               (lambda t: wf.set_template(t, wf.RELEASE, " ", [[QUALITY]]), "needs a name"),
               (lambda t: wf.set_template(t, "revise", "T", [[QUALITY]]), "can't have a workflow"))
        for change, text in bad:
            with self.subTest(text=text):
                with self.assertRaises(LitterboxError) as ctx:
                    with self.user("Alex"):
                        wf.edit_templates(self.a, lambda t, d, c=change: c(t), "x")
                self.assertIn(text.split()[0], str(ctx.exception))
                self.assertFalse((self.a / layout.WORKFLOWS_FILE).exists())
                self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_duplicate_names_are_refused(self):
        self.set_template()
        with self.assertRaises(LitterboxError) as ctx:
            with self.user("Alex"):
                wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, "t", [[QUALITY]]), "x")
        self.assertIn("already a Release workflow", str(ctx.exception))

    def test_role_spelling_is_tidied_to_the_orgs(self):
        self.set_template(rows=(("quality", "chief"),))
        self.assertEqual(wf.templates_for(self.a, wf.RELEASE)["T"].rows[0].roles, [QUALITY, CHIEF])

    def test_renaming_keeps_the_position_and_removing_the_last_drops_the_action(self):
        templates = {}
        for name in ("T1", "T2", "T3"):
            wf.set_template(templates, wf.RELEASE, name, [[QUALITY]])
        wf.set_template(templates, wf.RELEASE, "Flight", [[ENGINEER]], old_name="T2")
        self.assertEqual(list(templates[wf.RELEASE]), ["T1", "Flight", "T3"])
        for name in ("T1", "Flight", "T3"):
            wf.remove_template(templates, wf.RELEASE, name)
        self.assertEqual(templates, {})

    def test_standard_workflows_need_their_roles(self):
        directory = people.load(self.a)
        directory.roles = [ENGINEER, MANAGER]
        templates = {}
        missing = wf.add_standard(templates, directory)
        self.assertEqual(missing, ["Manufacturing", "Analysis", CHIEF])
        self.assertEqual(list(templates[wf.RELEASE]), ["T1", "T2", "T3"])
        self.assertEqual(set(templates), set(wf.ACTIONS))
        again = wf.add_standard(templates, directory)
        self.assertEqual(len(templates[wf.RELEASE]), 3)
        self.assertEqual(again, missing)

    def test_the_old_format_gets_a_clear_message(self):
        (self.a / ".litterbox").mkdir(exist_ok=True)
        (self.a / layout.WORKFLOWS_FILE).write_text("workflows:\n  release:\n    signoffs:\n    - role: Quality\n")
        with self.assertRaises(LitterboxError) as ctx:
            wf.load(self.a)
        self.assertIn("Litterbox 0.2", str(ctx.exception))

    def test_people_for_a_row_include_everyone_with_any_of_its_roles(self):
        directory = people.load(self.a)
        self.assertEqual([p.id for p in wf.eligible(directory, [MANAGER, QUALITY])], ["bea", "cy"])
        directory.people[1].active = False
        self.assertEqual([p.id for p in wf.eligible(directory, [MANAGER, QUALITY])], ["cy"])

    def test_warnings(self):
        directory = people.load(self.a)
        t = wf.Template(wf.RELEASE, "T", [wf.Row(["Manufacturing"]), wf.Row([QUALITY])])
        self.assertEqual(len(wf.role_warnings(t, directory)), 1)
        self.assertIn("nobody active", wf.role_warnings(t, directory)[0])
        t = wf.Template(wf.RELEASE, "T", [wf.Row([QUALITY]), wf.Row([QUALITY])])
        self.assertIn("enough different people", wf.role_warnings(t, directory)[0])
        t.allow_same_person = True
        self.assertEqual(wf.role_warnings(t, directory), [])
        t = wf.Template(wf.RELEASE, "T", [wf.Row([QUALITY, MANAGER]), wf.Row([QUALITY])])
        self.assertEqual(wf.role_warnings(t, directory), [])

    def test_a_vault_without_a_team_cannot_have_workflows(self):
        with mock.patch.object(people, "require", return_value=people.Identity(people.LEGACY)):
            with self.assertRaises(LitterboxError) as ctx:
                wf.edit_templates(self.a, lambda t, d: None, "x")
        self.assertIn("Set up the team", str(ctx.exception))


class TestWithoutAWorkflowThingsWorkAsBefore(Fixture, unittest.TestCase):
    def test_plain_release(self):
        self.do("Alex", lifecycle.release, PART)
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_direct_actions_are_refused_once_there_are_templates(self):
        for action, call in ((wf.RELEASE, lambda r: lifecycle.release(r, PART)),
                             (wf.MAKE_COTS, lambda r: lifecycle.make_cots(r, PART)),
                             (wf.VOID, lambda r: lifecycle.void(r, PART, "no")),
                             (wf.REOPEN, lambda r: lifecycle.reopen(r, PART, "no"))):
            with self.subTest(action=action):
                self.set_template(action)
                with self.assertRaises(LitterboxError) as ctx:
                    self.do("Alex", call)
                self.assertIn("needs sign-offs", str(ctx.exception))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)

    def test_requesting_without_a_template_says_so(self):
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"])
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
            self.do("Alex", wf.request, [PART, PART2], wf.RELEASE, "T", ["bea", "alex"])
        self.assertIn(str(PART2), str(ctx.exception))
        self.assertIn("checked out by", str(ctx.exception))
        self.assertEqual(self.record(PART).pending, {})

    def test_the_template_is_copied_into_the_request(self):
        self.request()
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, "T", [[QUALITY]], old_name="T"), "x")
        self.assertEqual(len(wf.templates_for(self.a, wf.RELEASE)["T"].rows), 1)
        self.assertEqual(len(self.record().pending["template"]["signoffs"]), 2)

    def test_the_people_named_must_fit_the_rows(self):
        self.set_template()
        cases = ((["cy", "alex"], "not active with the role"),
                 (["bea"], "Choose a person for every"), (["bea", ""], "Choose a person for sign-off 2"),
                 (["bea", "nobody"], "Choose a person"))
        for assign, text in cases:
            with self.subTest(assign=assign):
                with self.assertRaises(LitterboxError) as ctx:
                    self.do("Alex", wf.request, [PART], wf.RELEASE, "T", assign)
                self.assertIn(text, str(ctx.exception))
        self.assertEqual(self.record().pending, {})

    def test_one_person_cannot_fill_two_rows_unless_allowed(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["alex", "alex"])
        self.assertIn("doesn't let one person", str(ctx.exception))

    def test_the_same_person_may_fill_two_rows_when_the_template_says_so(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)), same=True)
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["alex", "alex"])
        self.assertEqual([s["id"] for s in self.record().pending["slots"]], ["alex", "alex"])

    def test_the_requester_may_be_barred_from_signing(self):
        self.set_template(requester=False)
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"])
        self.assertIn("sign your own request", str(ctx.exception))

    def test_optional_extra_sign_offs(self):
        self.set_template()
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"], extras=[(MANAGER, "cy")])
        slots = self.record().pending["slots"]
        self.assertEqual((len(slots), slots[2]["id"], slots[2].get("extra")), (3, "cy", True))
        with self.assertRaises(LitterboxError):
            self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"], extras=[("Wizard", "cy")])

    def test_or_rows_accept_anyone_with_any_of_the_roles(self):
        self.set_template(rows=((MANAGER, CHIEF),))
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["cy"])
        self.assertEqual(self.record().pending["slots"][0]["roles"], [MANAGER, CHIEF])
        self.assertIn("Manager or Chief", wf.slot_text(self.record().pending["slots"][0]))

    def test_reopen_and_void_need_a_reason(self):
        self.do("Alex", lifecycle.release, PART)
        self.set_template(wf.REOPEN, rows=((MANAGER,),))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.request, [PART], wf.REOPEN, "T", ["cy"])
        self.assertIn("reason is required", str(ctx.exception))
        self.do("Alex", wf.request, [PART], wf.REOPEN, "T", ["cy"], reason="Fix a drawing error")
        self.assertEqual(self.record().pending["reason"], "Fix a drawing error")

    def test_actions_that_cannot_happen_are_refused_up_front(self):
        self.set_template(wf.REOPEN, rows=((MANAGER,),))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.request, [PART], wf.REOPEN, "T", ["cy"], reason="x")
        self.assertIn("status is", str(ctx.exception))

    def test_a_pending_part_cannot_be_checked_out_or_changed(self):
        self.request()
        self.get_latest("Bea")
        for user, func in (("Alex", lambda r: checkout.checkout(r, PART)), ("Bea", lambda r: checkout.checkout(r, PART)),
                           ("Alex", lambda r: wf.request(r, [PART], wf.RELEASE, "T", ["bea", "alex"]))):
            with self.subTest(user=user):
                with self.user(user), self.assertRaises(LitterboxError):
                    func(self.repo_of(user))

    def test_someone_not_on_the_team_cannot_ask(self):
        self.set_template()
        with self.user("Zed"):
            with self.assertRaises(LitterboxError):
                wf.request(self.b, [PART], wf.RELEASE, "T", ["bea", "alex"])

    def test_the_record_round_trips(self):
        self.request()
        again = record_model.Record.from_dict(__import__("yaml").safe_load(record_model.dump(self.record())))
        self.assertEqual(again.pending, self.record().pending)


class TestSigning(Fixture, unittest.TestCase):
    def test_the_last_signature_releases(self):
        self.request()
        r = self.do("Alex", wf.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertEqual(self.record().status, record_model.STATUS_IN_WORK)
        self.get_latest("Bea")
        r = self.do("Bea", wf.sign_off, [PART], "Looks good")
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_RELEASED, "A", {}))
        self.assertEqual(lfs_locks.get_locks(self.a), {})

    def test_the_trail_is_kept_in_approvals(self):
        self.request()
        self.do("Alex", wf.sign_off, [PART])
        self.get_latest("Bea")
        self.do("Bea", wf.sign_off, [PART], "Looks good")
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
            self.do("Alex", wf.sign_off, [PART, PART2])           # one for Alex's signatures
            self.get_latest("Bea")
            self.do("Bea", wf.sign_off, [PART, PART2])            # one for hers, one for the release itself
        self.assertEqual(requested, 1)
        self.assertEqual(sum(1 for c in seen if c == "git push"), 4)
        self.assertEqual(sum(1 for c in seen if c.startswith("git commit")), 4)      # one commit per step, not per part
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_a_batch_is_signed_once_for_every_part(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", wf.sign_off, [PART, PART2])
        self.get_latest("Bea")
        r = self.do("Bea", wf.sign_off, [PART, PART2])
        self.assertEqual(sorted(map(str, r.completed)), sorted(map(str, [PART, PART2])))
        for pn in (PART, PART2):
            self.assertEqual(self.record(pn).status, record_model.STATUS_RELEASED)

    def test_signing_again_or_when_not_named_does_nothing(self):
        self.request()
        self.do("Alex", wf.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.sign_off, [PART])
        self.assertIn("nothing for you to sign", str(ctx.exception))
        with self.assertRaises(LitterboxError):
            self.do("Cy", wf.sign_off, [PART])

    def test_one_person_named_twice_signs_both_at_once(self):
        self.set_template(rows=((ENGINEER,), (ENGINEER,)), same=True)
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["alex", "alex"])
        r = self.do("Alex", wf.sign_off, [PART])
        self.assertEqual(r.completed, [PART])

    def test_a_failed_completion_keeps_the_signature_and_can_be_finished_later(self):
        self.request()
        self.do("Alex", wf.sign_off, [PART])
        self.get_latest("Bea")
        real = wf._finish_many
        wf._finish_many = lambda repo, pns, **k: (_ for _ in ()).throw(LitterboxError("offline"))
        try:
            r = self.do("Bea", wf.sign_off, [PART])
        finally:
            wf._finish_many = real
        self.assertEqual((r.signed, r.completed, r.errors), ([PART], [], {PART: "offline"}))
        self.get_latest("Alex")
        row = next(x for x in self.do("Alex", part_status.get_status) if x.pn == PART)
        self.assertEqual((row.kind, row.state), ("pending", "Release approved - ready to complete"))
        self.assertEqual(self.do("Alex", wf.complete, PART), [DRW, PRT])
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_completing_before_everyone_signed_is_refused(self):
        self.request()
        self.do("Alex", wf.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.complete, PART)
        self.assertIn("Quality (Bea Jones)", str(ctx.exception))

    def test_a_file_changed_since_the_request_stops_signing(self):
        self.request()
        self.get_latest("Bea")
        (self.b / PRT).chmod(0o644)
        (self.b / PRT).write_bytes(b"someone sneaked a change in")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", wf.sign_off, [PART])
        self.assertIn("different from the file", str(ctx.exception))
        git(self.b, "checkout", "--", str(PRT))

    def test_reopen_completes_automatically(self):
        self.do("Alex", lifecycle.release, PART)
        self.set_template(wf.REOPEN, rows=((MANAGER, CHIEF),))
        self.do("Alex", wf.request, [PART], wf.REOPEN, "T", ["cy"], reason="Drawing error")
        r = self.do("Cy", wf.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (record_model.STATUS_IN_WORK, "", {}))
        self.assertEqual([e for e in record.history if e["event"] == "reopened"][-1]["reason"], "Drawing error")
        self.assertEqual(record.approvals[-1]["reason"], "Drawing error")

    def test_void_completes_automatically(self):
        self.set_template(wf.VOID, rows=((MANAGER,),))
        self.do("Alex", wf.request, [PART], wf.VOID, "T", ["cy"], reason="Not needed")
        r = self.do("Cy", wf.sign_off, [PART])
        self.assertEqual(r.completed, [PART])
        self.assertEqual(self.record().status, record_model.STATUS_VOID)

    def test_make_cots_waits_for_someone_to_complete_it(self):
        self.set_template(wf.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", wf.request, [PART], wf.MAKE_COTS, "T", ["alex"])
        r = self.do("Alex", wf.sign_off, [PART])
        self.assertEqual((r.signed, r.completed), ([PART], []))
        self.assertTrue(wf.is_complete(self.record().pending))
        self.assertFalse(self.record().cots)
        self.do("Alex", wf.complete, PART)
        self.assertTrue(self.record().cots)
        self.assertEqual(self.record().pending, {})


class TestRejectingWithdrawingReassigning(Fixture, unittest.TestCase):
    def test_rejecting_sends_the_whole_batch_back(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", wf.sign_off, [PART, PART2])
        self.get_latest("Bea")
        self.do("Bea", wf.reject, [PART, PART2], "Wrong tolerance")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.pending, record.status), ({}, record_model.STATUS_IN_WORK))
            last = record.history[-1]
            self.assertEqual((last["event"], last["reason"], last["signed"]), ("release_rejected", "Wrong tolerance",
                                                                               ["Alex Smith"]))

    def test_a_reason_is_required_to_reject(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", wf.reject, [PART], "  ")

    def test_only_named_signers_or_admins_reject(self):
        self.request()
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Cy", wf.reject, [PART], "no")
        self.assertIn("named to sign", str(ctx.exception))
        self.assertTrue(self.record().pending)

    def test_the_requester_can_withdraw_but_other_members_cannot(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", wf.withdraw, [PART])
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", wf.withdraw, [PART], "Changed my mind")
        self.assertEqual(self.record().pending, {})
        self.assertEqual(self.record().history[-1]["event"], "release_withdrawn")

    def test_after_a_withdrawal_a_new_request_can_be_made(self):
        self.request()
        self.do("Alex", wf.withdraw, [PART])
        self.request()
        self.assertTrue(self.record().pending)

    def test_the_requester_can_change_who_signs(self):
        self.set_template(rows=((QUALITY, MANAGER), (ENGINEER,)))
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", wf.reassign, [PART], 0, "cy")
        slot = self.record().pending["slots"][0]
        self.assertEqual((slot["id"], slot["name"]), ("cy", "Cy Day"))
        self.assertEqual(self.record().history[-1]["event"], "workflow_reassigned")

    def test_reassigning_respects_the_rules(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.reassign, [PART], 0, "cy")                # Cy has no Quality role
        self.assertIn("not active with the role", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", wf.reassign, [PART], 0, "bea")
        self.assertIn("person who asked", str(ctx.exception))
        self.do("Alex", wf.sign_off, [PART])
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Alex", wf.reassign, [PART], 1, "alex")
        self.assertIn("already been given", str(ctx.exception))


class TestOverride(Fixture, unittest.TestCase):
    def test_a_member_cannot_override(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(LitterboxError) as ctx:
            self.do("Bea", wf.override, [PART], "urgent")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_a_reason_is_required(self):
        self.request()
        with self.assertRaises(LitterboxError):
            self.do("Alex", wf.override, [PART], " ")

    def test_an_admin_releases_a_batch_without_the_sign_offs(self):
        self.second_part()
        self.request(pns=(PART, PART2))
        self.do("Alex", wf.override, [PART, PART2], "Customer deadline")
        for pn in (PART, PART2):
            record = self.record(pn)
            self.assertEqual((record.status, record.pending), (record_model.STATUS_RELEASED, {}))
            released = [e for e in record.history if e["event"] == "released"][-1]
            self.assertTrue(released["override"])
            self.assertEqual(record.approvals[-1]["override"]["reason"], "Customer deadline")
            self.assertEqual(len(record.approvals[-1]["override"]["missing"]), 2)

    def test_an_admin_can_act_with_no_request_at_all(self):
        self.set_template()
        self.do("Alex", wf.override, [PART], "Urgent", action=wf.RELEASE)
        self.assertEqual(self.record().status, record_model.STATUS_RELEASED)

    def test_an_override_can_void_with_its_reason(self):
        self.set_template(wf.VOID, rows=((MANAGER,),))
        self.do("Alex", wf.override, [PART], "Duplicate part", action=wf.VOID)
        self.assertEqual(self.record().status, record_model.STATUS_VOID)


def identity_for(person_id, directory, access=people.MEMBER):
    person = directory.get(person_id)
    return SimpleNamespace(state=people.OK, person=person, directory=directory)


class TestTasks(Fixture, unittest.TestCase):
    def rows(self, user="Alex"):
        return self.do(user, part_status.get_status)

    def tasks(self, who, user="Alex"):
        return wf.tasks_from_rows(self.rows(user), identity_for(who, people.load(self.a)))

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
        self.do("Alex", wf.sign_off, [PART])                           # only one of the two parts
        (t,) = self.tasks("alex")
        self.assertTrue(t.can_sign)                                    # still something to sign on the other
        self.assertFalse(t.slots[1]["done"])

    def test_an_approved_request_waits_on_its_requester_to_complete(self):
        self.set_template(wf.MAKE_COTS, rows=((ENGINEER,),))
        self.do("Alex", wf.request, [PART], wf.MAKE_COTS, "T", ["alex"])
        self.do("Alex", wf.sign_off, [PART])
        (t,) = self.tasks("alex")
        self.assertEqual((t.ready, t.can_complete, wf.count_for_me([t])), (True, True, 1))

    def test_nobody_can_act_without_a_team_identity(self):
        self.request()
        ident = SimpleNamespace(state=people.NOT_LISTED, person=None, directory=None)
        (t,) = wf.tasks_from_rows(self.rows(), ident)
        self.assertFalse(any((t.can_sign, t.can_reject, t.can_complete, t.can_withdraw, t.can_override)))

    def test_things_waiting_on_me_come_first(self):
        self.second_part()
        self.request(pns=(PART,), assign=("cy", "alex")) if False else None
        self.set_template()
        self.do("Alex", wf.request, [PART], wf.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", wf.request, [PART2], wf.RELEASE, "T", ["bea", "alex"])
        self.do("Alex", wf.sign_off, [PART2])
        tasks = self.tasks("alex")
        self.assertEqual([str(t.pns[0]) for t in tasks], [str(PART), str(PART2)])


class TestDescribing(unittest.TestCase):
    def pending(self, signed=()):
        return {"action": "release", "slots": [{"roles": ["Quality"], "id": "bea", "name": "Bea"},
                                               {"roles": ["Manager", "Chief"], "id": "cy", "name": "Cy"}],
                "signoffs": [{"slot": i} for i in signed]}

    def test_progress_text(self):
        self.assertEqual(wf.describe_pending(self.pending()), "Release pending 0/2: waiting on Bea, Cy")
        self.assertEqual(wf.describe_pending(self.pending([0])), "Release pending 1/2: waiting on Cy")
        self.assertEqual(wf.describe_pending(self.pending([0, 1])), "Release approved - ready to complete")
        self.assertEqual(wf.waiting_on(self.pending([0])), ["Manager or Chief (Cy)"])

    def test_open_slots_and_may_sign(self):
        p = self.pending([0])
        person = SimpleNamespace(id="cy")
        self.assertEqual(wf.open_slots(p, "cy"), [1])
        self.assertEqual(wf.open_slots(p, "bea"), [])
        self.assertEqual(wf.may_sign(p, person), (True, ""))
        self.assertIn("already signed", wf.may_sign(p, SimpleNamespace(id="bea"))[1])
        self.assertIn("not one of the people", wf.may_sign(p, SimpleNamespace(id="zed"))[1])


if __name__ == "__main__":
    unittest.main()
