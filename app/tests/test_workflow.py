"""
Tests for workflow.py: sign-offs before a release. Uses the two-user vault (Alex is the Owner and a Responsible
Engineer; Bea is a Member with the Quality role). They need Linux, macOS or WSL.
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from vault_fixture import DRW, PART, PRT, REC, SKIP_ON_WINDOWS, TwoUserVault, git  # noqa: E402

import litterbox_engine as eng  # noqa: E402
import people  # noqa: E402
import registry  # noqa: E402
import workflow as wf  # noqa: E402

ENGINEER, QUALITY = "Responsible Engineer", "Quality"


@SKIP_ON_WINDOWS
class Fixture(TwoUserVault):
    def setUp(self):
        super().setUp()
        quiet = mock.patch.object(eng, "LOG", lambda *_: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        with self.user("Alex"):
            people.setup_team(self.a, "Alex Smith", "alex@x.com")
            people.edit_directory(self.a, lambda d, who: (
                people.update_person(d, who, "alex", roles=[ENGINEER]),
                people.add_person(d, who, "bea", "Bea Jones", "bea@x.com", ["Bea"], people.MEMBER, [QUALITY])),
                "Team: add Bea")
        self.get_latest("Bea")

    def get_latest(self, user):
        repo = self.a if user == "Alex" else self.b
        with self.user(user):
            eng.get_latest(repo)

    def repo_of(self, user):
        return self.a if user == "Alex" else self.b

    def set_template(self, steps=((QUALITY, 1), (ENGINEER, 1)), allow_self=True):
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, steps, allow_self), "Workflow")
        self.get_latest("Bea")

    def do(self, user, func, *args, **kwargs):
        with self.user(user):
            return func(self.repo_of(user), *args, **kwargs)

    def record(self):
        return registry.load(self.a, PART)

    def request(self):
        self.set_template() if not wf.load(self.a) else None
        return self.do("Alex", wf.request_release, PART)


class TestTemplates(Fixture, unittest.TestCase):
    def test_no_file_means_no_workflows(self):
        self.assertEqual(wf.load(self.a), {})
        self.assertIsNone(wf.template_for(self.a, wf.RELEASE))

    def test_an_admin_saves_a_template_for_everyone(self):
        self.set_template(((QUALITY, 2), (ENGINEER, 1)), allow_self=False)
        for repo in (self.a, self.b):
            template = wf.template_for(repo, wf.RELEASE)
            self.assertEqual([(s.role, s.count) for s in template.steps], [(QUALITY, 2), (ENGINEER, 1)])
            self.assertFalse(template.allow_self_signoff)
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        self.assertEqual(eng.get_locks(self.a), {})

    def test_a_vault_with_a_workflow_asks_for_the_new_version(self):
        import config
        import version
        self.assertNotIn("min_litterbox_version", config.load(self.a))
        self.set_template()
        for repo in (self.a, self.b):
            self.assertEqual(config.load(repo)["min_litterbox_version"], wf.MIN_VERSION)
        with mock.patch.object(version, "VERSION", "0.1.1"):
            with self.assertRaises(config.ConfigError) as ctx:
                config.check_compatible(self.b)
        self.assertIn("needs Litterbox 0.2.0", str(ctx.exception))

    def test_removing_every_workflow_does_not_lower_the_minimum(self):
        import config
        self.set_template()
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.remove_template(t, wf.RELEASE), "Remove")
        self.assertEqual(config.load(self.a)["min_litterbox_version"], wf.MIN_VERSION)

    def test_a_failed_save_leaves_the_config_alone_too(self):
        import config
        before = (self.a / ".litterbox" / "config.yaml").read_text() if (self.a / ".litterbox" / "config.yaml").exists() else None
        real = eng._push_with_retry
        eng._push_with_retry = lambda repo, attempts=3: (_ for _ in ()).throw(eng.LitterboxError("offline"))
        self.addCleanup(setattr, eng, "_push_with_retry", real)
        with self.assertRaises(eng.LitterboxError):
            with self.user("Alex"):
                wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, [(QUALITY, 1)]), "x")
        eng._push_with_retry = real
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        after = (self.a / ".litterbox" / "config.yaml").read_text() if (self.a / ".litterbox" / "config.yaml").exists() else None
        self.assertEqual(before, after)
        self.assertFalse((self.a / wf.WORKFLOWS_FILE).exists())
        self.assertEqual(eng.get_locks(self.a), {})

    def test_a_member_cannot_change_workflows(self):
        with self.assertRaises(eng.LitterboxError) as ctx:
            with self.user("Bea"):
                wf.edit_templates(self.b, lambda t, d: wf.set_template(t, wf.RELEASE, [(QUALITY, 1)]), "x")
        self.assertIn("Only an Admin", str(ctx.exception))
        self.assertFalse((self.b / wf.WORKFLOWS_FILE).exists())

    def test_bad_templates_are_refused_and_leave_nothing_behind(self):
        for steps, text in (([], "at least one"), ([("Wizard", 1)], "isn't one of this org's roles"),
                            ([(QUALITY, 1), ("quality", 1)], "twice"), ([(QUALITY, 0)], "whole number"),
                            ([(QUALITY, True)], "whole number"), ([(QUALITY, 99)], "whole number")):
            with self.subTest(steps=steps):
                with self.assertRaises(eng.LitterboxError) as ctx:
                    with self.user("Alex"):
                        wf.edit_templates(self.a, lambda t, d, s=steps: wf.set_template(t, wf.RELEASE, s), "x")
                self.assertIn(text, str(ctx.exception))
                self.assertFalse((self.a / wf.WORKFLOWS_FILE).exists())
                self.assertEqual(git(self.a, "status", "--porcelain"), "")

    def test_role_spelling_is_tidied_to_the_orgs(self):
        self.set_template((("quality", 1),))
        self.assertEqual(wf.template_for(self.a, wf.RELEASE).steps[0].role, QUALITY)

    def test_changing_an_existing_template_and_removing_it(self):
        self.set_template()
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, [(QUALITY, 1)]), "Change")
            self.assertEqual(len(wf.template_for(self.a, wf.RELEASE).steps), 1)
            wf.edit_templates(self.a, lambda t, d: wf.remove_template(t, wf.RELEASE), "Remove")
        self.assertIsNone(wf.template_for(self.a, wf.RELEASE))
        self.assertEqual(eng.get_locks(self.a), {})

    def test_roles_nobody_holds_are_warned_about(self):
        directory = people.load(self.a)
        template = wf.Template(wf.RELEASE, [wf.Step("Manufacturing", 1), wf.Step(QUALITY, 2), wf.Step(ENGINEER, 1)])
        warnings = wf.role_warnings(template, directory)
        self.assertEqual(len(warnings), 2)
        self.assertIn("nobody active has the role", warnings[0])
        self.assertIn("only 1 active person has the role", warnings[1])

    def test_a_vault_without_a_team_cannot_have_workflows(self):
        with mock.patch.object(people, "require", return_value=people.Identity(people.LEGACY)):
            with self.assertRaises(eng.LitterboxError) as ctx:
                wf.edit_templates(self.a, lambda t, d: None, "x")
        self.assertIn("Set up the team", str(ctx.exception))


class TestReleaseStillWorksWithoutAWorkflow(Fixture, unittest.TestCase):
    def test_plain_release(self):
        self.do("Alex", eng.release, PART)
        self.assertEqual(self.record().status, registry.STATUS_RELEASED)

    def test_plain_release_is_refused_once_there_is_a_template(self):
        self.set_template()
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", eng.release, PART)
        self.assertIn("need sign-offs", str(ctx.exception))
        self.assertEqual(self.record().status, registry.STATUS_IN_WORK)

    def test_requesting_without_a_template_says_so(self):
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.request_release, PART)
        self.assertIn("don't need sign-offs", str(ctx.exception))


class TestRequesting(Fixture, unittest.TestCase):
    def test_a_request_is_recorded_pushed_and_shown(self):
        text = self.request()
        self.assertEqual(text, "Release pending: Quality 0/1, Responsible Engineer 0/1")
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")
        record = self.record()
        pending = record.pending
        self.assertEqual((pending["requested_by"], pending["requested_by_id"], pending["revision"]),
                         ("Alex Smith", "alex", "A"))
        self.assertEqual(sorted(pending["files"]), [DRW, PRT])
        self.assertEqual(pending["signoffs"], [])
        self.assertEqual(record.history[-1]["event"], "release_requested")
        self.assertEqual(eng.get_locks(self.a), {})
        self.get_latest("Bea")
        row = next(r for r in self.do("Bea", eng.get_status) if r.pn == PART)
        self.assertEqual((row.kind, row.state), ("pending", text))

    def test_the_template_is_copied_into_the_request(self):
        self.request()
        with self.user("Alex"):
            wf.edit_templates(self.a, lambda t, d: wf.set_template(t, wf.RELEASE, [(QUALITY, 3)]), "Later change")
        self.assertEqual(len(self.record().pending["template"]["signoffs"]), 2)

    def test_a_pending_part_cannot_be_checked_out_changed_or_requested_again(self):
        self.request()
        self.get_latest("Bea")
        for user, func in (("Alex", lambda r: eng.checkout(r, PART)), ("Bea", lambda r: eng.checkout(r, PART)),
                           ("Alex", lambda r: eng.void(r, PART, "no")), ("Alex", lambda r: eng.make_cots(r, PART)),
                           ("Alex", lambda r: wf.request_release(r, PART)),
                           ("Alex", lambda r: eng.release_plan(r, PART)) ):
            with self.subTest(user=user):
                with self.user(user):
                    try:
                        result = func(self.repo_of(user))
                    except eng.LitterboxError:
                        continue
                    self.assertFalse(getattr(result, "ok", True))

    def test_blockers_stop_a_request_like_they_stop_a_release(self):
        self.set_template()
        with self.user("Bea"):
            eng.checkout(self.b, PART)
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.request_release, PART)
        self.assertIn("checked out by", str(ctx.exception))
        self.assertEqual(self.record().pending, {})

    def test_someone_not_on_the_team_cannot_ask(self):
        self.set_template()
        with self.user("Cy"):
            with self.assertRaises(eng.LitterboxError):
                wf.request_release(self.b, PART)

    def test_the_record_round_trips(self):
        self.request()
        again = registry.Record.from_dict(__import__("yaml").safe_load(registry._dump(self.record())))
        self.assertEqual(again.pending, self.record().pending)


class TestSigning(Fixture, unittest.TestCase):
    def test_partial_then_the_last_signature_releases(self):
        self.request()
        result = self.do("Alex", wf.sign_off, PART, "Looks good")
        self.assertFalse(result.completed)
        self.assertEqual(result.summary, "Release pending: Quality 0/1, Responsible Engineer 1/1")
        self.assertEqual(self.record().status, registry.STATUS_IN_WORK)

        result = self.do("Bea", wf.sign_off, PART)
        self.assertTrue(result.completed, result.error)
        self.get_latest("Alex")
        record = self.record()
        self.assertEqual((record.status, record.released_revision, record.pending), (registry.STATUS_RELEASED, "A", {}))
        released = record.history[-1]
        self.assertEqual((released["event"], released["by"], released["signoffs"]), ("released", "Bea Jones",
                                                                                      ["Alex Smith", "Bea Jones"]))
        events = [e["event"] for e in record.history]
        self.assertEqual(events[-4:], ["release_requested", "release_signed", "release_signed", "released"])
        self.assertEqual(self.record().history[-3]["comment"], "Looks good")

    def test_the_trail_is_kept_in_approvals(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        self.do("Bea", wf.sign_off, PART, "OK")
        self.get_latest("Alex")
        entry = self.record().approvals[-1]
        self.assertEqual((entry["action"], entry["revision"], entry["requested_by"], entry["completed_by"]),
                         ("release", "A", "Alex Smith", "Bea Jones"))
        self.assertEqual([(s["by"], s["roles"]) for s in entry["signoffs"]],
                         [("Alex Smith", [ENGINEER]), ("Bea Jones", [QUALITY])])
        self.assertEqual(sorted(entry["files"]), [DRW, PRT])
        self.assertEqual(len(entry["template"]["signoffs"]), 2)
        self.assertNotIn("override", entry)

    def test_the_released_files_are_frozen_like_any_release(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        self.do("Bea", wf.sign_off, PART)
        self.get_latest("Alex")
        with self.assertRaises(eng.LitterboxError):
            self.do("Alex", eng.checkout, PART)

    def test_a_person_cannot_sign_twice_or_without_the_role(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.sign_off, PART)
        self.assertIn("already signed", str(ctx.exception))
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.add_person(
                d, who, "cy", "Cy Park", "", ["Cy"], people.MEMBER, []), "Team: add Cy")
        self.get_latest("Bea")
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Cy", wf.sign_off, PART)
        self.assertIn("don't hold a role", str(ctx.exception))
        self.assertEqual(len(self.record().pending["signoffs"]), 1)

    def test_not_allowing_self_signoff(self):
        self.set_template(allow_self=False)
        self.do("Alex", wf.request_release, PART)
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.sign_off, PART)
        self.assertIn("your own request", str(ctx.exception))

    def test_one_person_holding_two_roles_signs_for_both(self):
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.update_person(
                d, who, "bea", roles=[QUALITY, ENGINEER]), "Team: Bea too")
        self.get_latest("Bea")
        self.request()
        result = self.do("Bea", wf.sign_off, PART)
        self.assertTrue(result.completed, result.error)

    def test_a_count_needs_different_people(self):
        self.set_template(((QUALITY, 2),))
        self.do("Alex", wf.request_release, PART)
        self.do("Bea", wf.sign_off, PART)
        self.get_latest("Alex")
        pending = self.record().pending
        self.assertEqual(wf.describe_pending(pending), "Release pending: Quality 1/2")
        with self.assertRaises(eng.LitterboxError):
            self.do("Bea", wf.sign_off, PART)

    def test_read_only_people_cannot_sign(self):
        self.request()
        with self.user("Cy"):
            with self.assertRaises(eng.LitterboxError):
                wf.sign_off(self.b, PART)

    def test_signing_with_nothing_pending(self):
        self.set_template()
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Bea", wf.sign_off, PART)
        self.assertIn("no release request", str(ctx.exception))

    def test_a_failed_completion_keeps_the_signature_and_can_be_finished_later(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        real = wf.complete_release
        wf.complete_release = lambda repo, pn: (_ for _ in ()).throw(eng.LitterboxError("offline"))
        try:
            result = self.do("Bea", wf.sign_off, PART)
        finally:
            wf.complete_release = real
        self.assertFalse(result.completed)
        self.assertEqual(result.error, "offline")
        self.assertEqual(result.summary, "Release approved - ready to complete")
        self.get_latest("Alex")
        row = next(r for r in self.do("Alex", eng.get_status) if r.pn == PART)
        self.assertEqual((row.kind, row.state), ("pending", "Release approved - ready to complete"))
        self.assertEqual(self.do("Alex", wf.complete_release, PART), [DRW, PRT])
        self.assertEqual(self.record().status, registry.STATUS_RELEASED)

    def test_completing_before_everyone_signed_is_refused(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.complete_release, PART)
        self.assertIn("Quality (0 of 1)", str(ctx.exception))

    def test_a_file_changed_since_the_request_stops_signing(self):
        self.request()
        self.get_latest("Bea")
        (self.b / PRT).chmod(0o644)
        (self.b / PRT).write_bytes(b"someone sneaked a change in")
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Bea", wf.sign_off, PART)
        self.assertIn("different from the file", str(ctx.exception))
        git(self.b, "checkout", "--", str(PRT))


class TestRejectingAndWithdrawing(Fixture, unittest.TestCase):
    def test_rejecting_sends_it_back(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        self.do("Bea", wf.reject, PART, "Drawing is missing a tolerance")
        self.get_latest("Alex")
        record = self.record()
        self.assertEqual((record.status, record.pending), (registry.STATUS_IN_WORK, {}))
        last = record.history[-1]
        self.assertEqual((last["event"], last["reason"], last["signed"]),
                         ("release_rejected", "Drawing is missing a tolerance", ["Alex Smith"]))
        self.do("Alex", eng.checkout, PART)                                       # in work again

    def test_a_reason_is_required_to_reject(self):
        self.request()
        with self.assertRaises(eng.LitterboxError):
            self.do("Bea", wf.reject, PART, "  ")

    def test_only_role_holders_or_admins_reject(self):
        self.request()
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.add_person(
                d, who, "cy", "Cy Park", "", ["Cy"], people.MEMBER, []), "Team: add Cy")
        self.get_latest("Bea")
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Cy", wf.reject, PART, "No")
        self.assertIn("Only people holding a role", str(ctx.exception))
        self.do("Alex", wf.reject, PART, "Admins may")                            # Alex is the Owner

    def test_the_requester_can_withdraw_but_other_members_cannot(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Bea", wf.withdraw, PART)
        self.assertIn("Only the person who asked", str(ctx.exception))
        self.do("Alex", wf.withdraw, PART, "Wrong revision")
        last = self.record().history[-1]
        self.assertEqual((last["event"], last["reason"]), ("release_withdrawn", "Wrong revision"))
        self.assertEqual(self.record().pending, {})

    def test_an_admin_can_withdraw_someone_elses_request(self):
        with self.user("Alex"):
            people.edit_directory(self.a, lambda d, who: people.update_person(
                d, who, "bea", roles=[QUALITY, ENGINEER]), "Team: Bea too")
        self.set_template()
        self.get_latest("Bea")
        self.do("Bea", wf.request_release, PART)
        self.get_latest("Alex")
        self.do("Alex", wf.withdraw, PART)
        self.assertEqual(self.record().pending, {})

    def test_after_a_withdrawal_a_new_request_can_be_made(self):
        self.request()
        self.do("Alex", wf.withdraw, PART)
        self.do("Alex", wf.request_release, PART)
        self.assertTrue(self.record().pending)


class TestOverride(Fixture, unittest.TestCase):
    def test_a_member_cannot_override(self):
        self.request()
        self.get_latest("Bea")
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Bea", wf.override_release, PART, "I'm in a hurry")
        self.assertIn("Only an Admin", str(ctx.exception))

    def test_a_reason_is_required(self):
        self.request()
        with self.assertRaises(eng.LitterboxError):
            self.do("Alex", wf.override_release, PART, " ")

    def test_an_admin_releases_with_a_pending_request(self):
        self.request()
        self.do("Alex", wf.sign_off, PART)
        self.do("Alex", wf.override_release, PART, "Quality is on holiday")
        record = self.record()
        self.assertEqual((record.status, record.pending), (registry.STATUS_RELEASED, {}))
        event = record.history[-1]
        self.assertEqual((event["event"], event["override"], event["reason"]), ("released", True, "Quality is on holiday"))
        entry = record.approvals[-1]
        self.assertEqual((entry["override"]["by"], entry["override"]["reason"], entry["override"]["missing"]),
                         ("Alex Smith", "Quality is on holiday", ["Quality (0 of 1)"]))
        self.assertEqual(len(entry["signoffs"]), 1)

    def test_an_admin_releases_with_no_request_at_all(self):
        self.set_template()
        self.do("Alex", wf.override_release, PART, "Urgent")
        record = self.record()
        self.assertEqual(record.status, registry.STATUS_RELEASED)
        entry = record.approvals[-1]
        self.assertEqual(entry["override"]["missing"], [QUALITY, ENGINEER])
        self.assertEqual(sorted(entry["files"]), [DRW, PRT])

    def test_without_a_template_there_is_nothing_to_override(self):
        with self.assertRaises(eng.LitterboxError) as ctx:
            self.do("Alex", wf.override_release, PART, "Urgent")
        self.assertIn("Use Release normally", str(ctx.exception))


class TestTasks(unittest.TestCase):
    def identity(self, person_id, roles, access=people.MEMBER):
        person = people.Person(person_id, person_id.title(), "", [person_id], access, roles)
        return SimpleNamespace(state=people.OK, person=person)

    def row(self, name="Part", signed=(), requested_by="alex", steps=((QUALITY, 1),), allow_self=True):
        pending = {"action": "release", "revision": "A", "requested_by": requested_by.title(),
                   "requested_by_id": requested_by, "requested_at": "2026-10-11T00:00:00Z",
                   "template": {"allow_self_signoff": allow_self,
                                "signoffs": [{"role": r, "count": c} for r, c in steps]},
                   "files": {}, "signoffs": [{"by": s.title(), "id": s, "roles": [r]} for s, r in signed]}
        return SimpleNamespace(pn=name, name=name, pending=pending)

    def test_nothing_pending_means_no_tasks(self):
        self.assertEqual(wf.tasks_from_rows([SimpleNamespace(pn="X", name="X", pending={})], self.identity("bea", [QUALITY])), [])

    def test_a_role_holder_can_sign_and_reject(self):
        tasks = wf.tasks_from_rows([self.row()], self.identity("bea", [QUALITY]))
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertTrue(task.can_sign and task.can_reject)
        self.assertFalse(task.can_withdraw or task.can_override or task.can_complete)
        self.assertEqual(wf.count_for_me(tasks), 1)

    def test_someone_without_the_role_only_looks(self):
        task = wf.tasks_from_rows([self.row()], self.identity("cy", []))[0]
        self.assertFalse(task.can_sign or task.can_reject)
        self.assertIn("don't hold a role", task.why_not_sign)

    def test_the_requester_can_withdraw_and_an_admin_can_override(self):
        task = wf.tasks_from_rows([self.row()], self.identity("alex", []))[0]
        self.assertTrue(task.mine and task.can_withdraw)
        admin = wf.tasks_from_rows([self.row()], self.identity("zed", [], people.ADMIN))[0]
        self.assertTrue(admin.can_override and admin.can_withdraw and admin.can_reject)

    def test_an_approved_request_waits_on_its_requester_to_complete(self):
        row = self.row(signed=[("bea", QUALITY)])
        mine = wf.tasks_from_rows([row], self.identity("alex", []))
        self.assertTrue(mine[0].ready and mine[0].can_complete)
        self.assertEqual(wf.count_for_me(mine), 1)
        other = wf.tasks_from_rows([row], self.identity("cy", []))
        self.assertEqual(wf.count_for_me(other), 0)

    def test_nobody_can_act_without_a_team_identity(self):
        legacy = SimpleNamespace(state=people.LEGACY, person=None)
        task = wf.tasks_from_rows([self.row()], legacy)[0]
        self.assertFalse(any((task.can_sign, task.can_reject, task.can_complete, task.can_withdraw, task.can_override)))

    def test_things_waiting_on_me_come_first(self):
        rows = [self.row("A-first", steps=((ENGINEER, 1),)), self.row("B-second")]
        tasks = wf.tasks_from_rows(rows, self.identity("bea", [QUALITY]))
        self.assertEqual([t.name for t in tasks], ["B-second", "A-first"])

    def test_self_signoff_off_hides_the_sign_button_from_the_requester(self):
        task = wf.tasks_from_rows([self.row(allow_self=False)], self.identity("alex", [QUALITY]))[0]
        self.assertFalse(task.can_sign)
        self.assertIn("your own request", task.why_not_sign)


class TestDescribing(unittest.TestCase):
    def test_progress_counts_distinct_people_per_role(self):
        pending = {"template": {"signoffs": [{"role": QUALITY, "count": 2}, {"role": ENGINEER, "count": 1}]},
                   "signoffs": [{"by": "Bea", "id": "bea", "roles": [QUALITY]},
                                {"by": "Bea", "id": "bea", "roles": [QUALITY]}]}
        steps = wf.progress(pending)
        self.assertEqual([(s.role, s.have, s.need) for s in steps], [(QUALITY, 1, 2), (ENGINEER, 0, 1)])
        self.assertEqual(wf.waiting_on(pending), ["Quality (1 of 2)", "Responsible Engineer (0 of 1)"])
        self.assertFalse(wf.is_complete(pending))


if __name__ == "__main__":
    unittest.main()
