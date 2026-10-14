"""Tests for workflow templates and saving them (workflow_templates, workflow_store, workflow_editing). Uses the two-user vault (Alex is the Owner and a Responsible Engineer; Bea is a Member with the Quality role; Cy is listed with the Manager role). They need Linux, macOS or WSL."""

import unittest
from unittest import mock
from tests.support.vault_fixture import PART, git
from litterbox.team import team_identity
from litterbox.team import team_permissions
from litterbox.team import team_store
from litterbox.records import record_model
from litterbox.workflows import workflow_editing
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates
from tests.support.workflow_fixture import CHIEF, ENGINEER, MANAGER, QUALITY, Fixture
from litterbox.errors import LitterboxError
from litterbox import layout
from litterbox.git import lfs_locks
from litterbox.parts import lifecycle
from litterbox.git import remote


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


if __name__ == "__main__":
    unittest.main()
