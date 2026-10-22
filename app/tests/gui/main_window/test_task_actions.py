"""Tests for sign-off workflows and My Tasks in the main window. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes, replace


class WorkflowWiring(unittest.TestCase):
    """The window side of workflows: starting one, My Tasks, and the Workflows window."""

    def setUp(self):
        from types import SimpleNamespace
        self.SimpleNamespace = SimpleNamespace
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.app.App.__new__(self.gui.app.App)
        self.tasks, self.said = [], []
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, done, on_success))
        app._say = lambda text, tone="normal": self.said.append(text)
        app.repo = lambda: "C:/vault"
        app.rows, app.rows_by_pn = [], {}
        directory = self.gui.team_model.Directory(
            [self.gui.team_model.Person("alex", "Alex", "", ["Alex"], "owner", ["Responsible Engineer"]),
             self.gui.team_model.Person("bea", "Bea", "", ["Bea"], "member", ["Quality"])],
            ["Responsible Engineer", "Quality"])
        self.directory = directory
        app.identity = SimpleNamespace(state="ok", directory=directory, person=directory.get("alex"))
        app.note = ""
        self.asked = []
        app._ask = lambda text, title: self.asked.append((text, title)) or self.answer
        self.answer = ""
        self.app = app
        self.templates = {"T1": self.gui.workflow_templates.Template("release", "T1", [self.gui.workflow_templates.Row(["Quality"])])}
        replace(self, self.gui.workflow_store, "templates_for", lambda repo, action: self.templates)
        self.made_after = []
        replace(self, self.gui.generate_files, "after_release",
                lambda repo, pns: self.made_after.append(pns) or self.gui.generate_files.Generated())

    def row(self, kind, pending=None, pn="HCR-00001-001"):
        return self.SimpleNamespace(pn=pn, name="Upright", kind=kind, state=kind, pending=pending or {})

    def pending(self, signed=False, action="release", batch="b1"):
        return {"id": batch, "action": action, "revision": "A", "requested_by": "Alex", "requested_by_id": "alex",
                "requested_at": "2026-10-11T00:00:00Z", "template_name": "T1", "template": {}, "files": {},
                "parts": ["HCR-00001-001"], "slots": [{"roles": ["Quality"], "id": "bea", "name": "Bea"}],
                "signoffs": [{"slot": 0, "by": "Bea", "id": "bea"}] if signed else []}

    def task(self, **changes):
        base = dict(id="b1", label="HCR-00001-001", action="release", pns=["HCR-00001-001"],
                    slots=[{"text": "Quality", "name": "Bea", "done": False, "roles": ["Quality"]}])
        base.update(changes)
        return self.SimpleNamespace(**base)

    def shown(self, name):
        return [call for call in self.box.calls if call[0] == name]

    def targets(self, *pns):
        self.app._plan = lambda action: self.SimpleNamespace(targets=list(pns), skipped=[])

    def test_release_in_a_vault_with_a_workflow_opens_the_workflow_window(self):
        self.targets("HCR-00001-001", "HCR-00002-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok"), "HCR-00002-001": self.row("ok", pn="HCR-00002-001")}
        seen = []

        class Dialog:
            def __init__(inner, parent, action, parts, templates, directory, my_id, addable):
                seen.append((action, parts, list(templates), my_id))

            def show(inner):
                return {"template": "T1", "assignments": ["bea"], "extras": [("Quality", "bea")], "reason": "",
                        "parts": ["HCR-00001-001", "HCR-00002-001"], "eco": None}

        self.gui.request_dialog.WorkflowRequestDialog = Dialog
        calls = []
        replace(self, self.gui.workflow_request, "request", lambda *a: calls.append(a) or "id")
        self.app.release()
        self.assertEqual(seen, [("release", [("HCR-00001-001", "Upright"), ("HCR-00002-001", "Upright")], ["T1"],
                                 "alex")])
        work, done, _ = self.tasks.pop()
        work()
        self.assertEqual(calls, [("C:/vault", ["HCR-00001-001", "HCR-00002-001"], "release", "T1", ["bea"],
                                  [("Quality", "bea")], "", None)])
        self.assertIn("2 parts", done)

    def test_the_parts_and_eco_chosen_in_the_window_are_used(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok"), "HCR-00002-001": self.row("ok", pn="HCR-00002-001"),
                               "HCR-00003-001": self.row("pending", pn="HCR-00003-001"),
                               "HCR-00004-001": self.row("ok", pn="HCR-00004-001")}
        self.app.jobs = self.SimpleNamespace(pending_parts=lambda: {"HCR-00004-001": "Checking in"})
        offered = []

        class Dialog:
            def __init__(inner, parent, action, parts, templates, directory, my_id, addable):
                offered.extend(str(r.pn) for r in addable(["HCR-00001-001"]))

            def show(inner):
                return {"template": "T1", "assignments": ["bea"], "extras": [], "reason": "",
                        "parts": ["HCR-00002-001"], "eco": {"name": "Bracket", "description": ""}}

        self.gui.request_dialog.WorkflowRequestDialog = Dialog
        calls = []
        replace(self, self.gui.workflow_request, "request", lambda *a: calls.append(a) or "id")
        self.app.release()
        self.assertEqual(offered, ["HCR-00002-001"])          # not one already in, waiting, or busy
        work, done, _ = self.tasks.pop()
        work()
        self.assertEqual(calls[0][1], ["HCR-00002-001"])
        self.assertEqual(calls[0][-1], {"name": "Bracket", "description": ""})
        self.assertIn("1 part", done)

    def test_cancelling_the_workflow_window_does_nothing(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok")}
        self.gui.request_dialog.WorkflowRequestDialog = lambda *a: self.SimpleNamespace(show=lambda: None)
        self.app.release()
        self.assertEqual(self.tasks, [])

    def test_reopen_void_and_make_cots_use_the_window_too(self):
        for action, method in (("reopen", "reopen"), ("void", "void"), ("make_cots", "make_cots")):
            with self.subTest(action=action):
                self.targets("HCR-00001-001")
                self.app.rows_by_pn = {"HCR-00001-001": self.row("ok")}
                opened = []
                self.gui.request_dialog.WorkflowRequestDialog = lambda parent, act, *a: opened.append(act) or self.SimpleNamespace(
                    show=lambda: None)
                getattr(self.app, method)()
                self.assertEqual(opened, [action])

    def plan(self, n, ok=True, problems=()):
        return self.SimpleNamespace(pn=f"HCR-0000{n}-001", name="Upright", files=["cad/a.SLDPRT"], warnings=[],
                                    problems=list(problems), ok=ok)

    def test_without_a_workflow_release_works_as_before(self):
        self.templates = {}
        released = []
        replace(self, self.gui.lifecycle, "release_many", lambda repo, pns: released.append(pns) or ([], []))
        self.app._confirm_release("C:/vault", [self.plan(1)])
        self.tasks.pop()[0]()
        self.assertEqual(released, [["HCR-00001-001"]])

    def test_without_a_workflow_several_parts_are_released_together(self):
        self.templates = {}
        self.targets("HCR-00001-001", "HCR-00002-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok"), "HCR-00002-001": self.row("ok", pn="HCR-00002-001")}
        looked = []
        replace(self, self.gui.planning, "release_plans", lambda repo, pns: looked.append(pns) or "plans")
        self.app.release()
        work, _done, on_success = self.tasks.pop()
        self.assertEqual(work(), "plans")
        self.assertEqual(looked, [["HCR-00001-001", "HCR-00002-001"]])

        released = []
        replace(self, self.gui.lifecycle, "release_many", lambda repo, pns: released.append(pns) or ([], []))
        self.app._confirm_release("C:/vault", [self.plan(1), self.plan(2), self.plan(3, False, ["Checked out by Bea."])])
        question = self.shown("askokcancel")[-1][1]
        self.assertIn("Release these 2 parts", question[1])
        self.assertIn("HCR-00003-001: Checked out by Bea.", question[1])      # the one that can't go is named
        self.tasks.pop()[0]()
        self.assertEqual(released, [["HCR-00001-001", "HCR-00002-001"]])      # and left out

    def test_void_and_unrelease_ask_one_reason_for_all_the_parts(self):
        self.templates = {}
        self.targets("HCR-00001-001", "HCR-00002-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok"), "HCR-00002-001": self.row("ok", pn="HCR-00002-001")}
        self.app._ask_reason = lambda text, title: "Because"
        got = []
        for name in ("void_many", "reopen_many"):
            replace(self, self.gui.lifecycle, name, lambda repo, pns, reason, name=name: got.append((name, pns, reason))
                    or ([], []))
        self.app.void()
        self.tasks.pop()[0]()
        self.app.reopen()
        self.tasks.pop()[0]()
        pair = ["HCR-00001-001", "HCR-00002-001"]
        self.assertEqual(got, [("void_many", pair, "Because"), ("reopen_many", pair, "Because")])

    def test_blockers_are_shown_instead_of_asking(self):
        self.app._confirm_release("C:/vault", [self.SimpleNamespace(
            pn="HCR-00001-001", problems=["It is checked out by Bea."], ok=False)])
        self.assertEqual(self.tasks, [])
        self.assertIn("checked out by Bea", self.shown("showwarning")[0][1][1])

    def test_the_button_on_a_waiting_part_says_what_is_missing(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("pending", self.pending())}
        self.app.release()
        self.assertEqual(self.tasks, [])
        self.assertIn("Quality (Bea)", self.shown("showinfo")[0][1][1])

    def test_the_button_on_a_part_with_a_different_request_says_so(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("pending", self.pending(action="void"))}
        self.app.release()
        self.assertEqual(self.tasks, [])
        self.assertIn("Void request waiting", self.shown("showinfo")[0][1][1])

    def test_the_button_on_an_approved_part_completes_it(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("pending", self.pending(signed=True))}
        done = []
        replace(self, self.gui.workflow_signoff, "complete_many", lambda repo, pns: done.append(pns))
        self.app.release()
        self.tasks.pop()[0]()
        self.assertEqual(done, [["HCR-00001-001"]])

    def test_approving_passes_the_comment_and_reports_a_failure(self):
        self.answer = "Looks right"
        seen = []
        replace(self, self.gui.workflow_signoff, "sign_off", lambda repo, pns, comment: seen.append((pns, comment)) or "result")
        self.app.task_sign(self.task())
        work, done, on_success = self.tasks.pop()
        result, files = work()
        self.assertEqual(result, "result")
        self.assertEqual(seen, [(["HCR-00001-001"], "Looks right")])
        self.assertEqual(self.made_after, [["HCR-00001-001"]])     # whatever it released gets its STEP and PDF
        on_success((self.SimpleNamespace(completed=[], errors={"HCR-00001-001": "offline"}), files))
        self.assertIn("offline", self.shown("showwarning")[0][1][1])
        on_success((self.SimpleNamespace(completed=["HCR-00001-001"], errors={}), files))
        self.assertIn("Release done on 1 part", self.app.note)

    def test_cancelling_the_comment_box_cancels_the_approval(self):
        self.answer = None
        self.app.task_sign(self.task())
        self.assertEqual(self.tasks, [])

    def test_rejecting_needs_a_reason(self):
        self.answer = "   "
        self.app.task_reject(self.task())
        self.assertEqual(self.tasks, [])
        self.assertIn("A reason is required", self.shown("showwarning")[0][1][1])
        self.answer = "Missing tolerance"
        seen = []
        replace(self, self.gui.workflow_responses, "reject", lambda repo, pns, reason: seen.append((pns, reason)))
        self.app.task_reject(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], "Missing tolerance")])

    def test_withdrawing_asks_first(self):
        self.box.answer = False
        self.app.task_withdraw(self.task())
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        gone = []
        replace(self, self.gui.workflow_responses, "withdraw", lambda repo, pns: gone.append(pns))
        self.app.task_withdraw(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(gone, [["HCR-00001-001"]])

    def test_completing_asks_first(self):
        self.box.answer = False
        self.app.task_complete(self.task())
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        done = []
        replace(self, self.gui.workflow_signoff, "complete_many", lambda repo, pns: done.append(pns))
        self.app.task_complete(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(done, [["HCR-00001-001"]])

    def test_an_override_needs_a_reason_and_a_confirmation(self):
        self.answer = ""
        self.app.task_override(self.task())
        self.assertEqual(self.tasks, [])
        self.answer = "Quality is away"
        self.box.answer = False
        self.app.task_override(self.task())
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        seen = []
        replace(self, self.gui.workflow_signoff, "override", lambda repo, pns, reason, action=None: seen.append((pns, reason, action)))
        self.app.task_override(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], "Quality is away", "release")])

    def test_changing_a_signer(self):
        self.gui.reassign_dialog.ReassignDialog = lambda parent, task, directory: self.SimpleNamespace(show=lambda: (0, "alex"))
        seen = []
        replace(self, self.gui.workflow_responses, "reassign", lambda repo, pns, slot, person: seen.append((pns, slot, person)))
        self.app.task_reassign(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], 0, "alex")])
        self.gui.reassign_dialog.ReassignDialog = lambda *a: self.SimpleNamespace(show=lambda: None)
        self.app.task_reassign(self.task())
        self.assertEqual(self.tasks, [])

    def test_approve_as_superuser_signs_the_ticked_sign_offs(self):
        seen, signed = [], []

        class Dialog:
            answer = ([0], "Bea is away")

            def __init__(inner, parent, task):
                seen.append(task.superuser_slots)

            def show(inner):
                return Dialog.answer

        replace(self, self.gui.superuser_sign_dialog, "SuperuserSignDialog", Dialog)
        replace(self, self.gui.workflow_signoff, "sign_as_superuser",
                lambda repo, pns, slots, comment: signed.append((pns, slots, comment)))
        self.app.task_superuser_sign(self.task(superuser_slots=[0]))
        work, done, _ = self.tasks.pop()
        work()
        self.assertEqual((seen, signed), ([[0]], [(["HCR-00001-001"], [0], "Bea is away")]))
        self.assertIn("as superuser", done)
        Dialog.answer = None                            # cancelled
        self.app.task_superuser_sign(self.task(superuser_slots=[0]))
        self.assertEqual(self.tasks, [])

    def test_override_reject_needs_a_reason_and_is_an_override(self):
        rejected = []
        replace(self, self.gui.workflow_responses, "reject",
                lambda repo, pns, reason, override=False: rejected.append((pns, reason, override)))
        self.app.task_override_reject(self.task())
        self.assertEqual(self.tasks, [])                # no reason given
        self.answer = "Wrong material"
        self.app.task_override_reject(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(rejected, [(["HCR-00001-001"], "Wrong material", True)])

    def test_the_workflows_screen_shows_all_workflows_only_to_admins_and_superusers(self):
        model = self.gui.team_model
        directory = model.Directory(
            [model.Person("alex", "Alex", "", ["Alex"], "owner", ["Responsible Engineer"]),
             model.Person("bea", "Bea", "", ["Bea"], "member", ["Quality"]),
             model.Person("cy", "Cy", "", ["Cy"], "member", ["Chief"]),
             model.Person("dee", "Dee", "", ["Dee"], "member", ["Quality"])],
            ["Responsible Engineer", "Quality", "Chief"], superuser_roles=["Chief"])
        self.app.rows = [self.row("pending", self.pending())]       # Alex asked, Bea signs

        def screen_for(person_id):
            self.app.identity = self.SimpleNamespace(state="ok", directory=directory, person=directory.get(person_id))
            return self.gui.tasks_screen.TasksScreen(FakeParent(), self.app)

        for person_id, all_tab, mine in (("alex", True, 1), ("bea", False, 1), ("cy", True, 0), ("dee", False, 0)):
            screen = screen_for(person_id)
            self.assertEqual((screen.everything is not None, len(screen.mine.tasks)), (all_tab, mine), person_id)
            if all_tab:
                self.assertEqual(len(screen.everything.tasks), 1)
        cy = screen_for("cy").everything.tasks["b1"]
        self.assertEqual(cy.superuser_slots, [0])
        text = self.gui.task_text
        self.assertEqual(text.all_workflows_buttons(self.app.identity), {"complete", "reassign", "withdraw", "superuser"})
        self.app.identity = self.SimpleNamespace(state="ok", directory=directory, person=directory.get("alex"))
        self.assertEqual(text.all_workflows_buttons(self.app.identity),
                         {"complete", "reassign", "withdraw", "override", "override_reject"})

    def test_refreshing_reloads_the_my_tasks_screen(self):
        reloaded = []
        self.app._task_windows = lambda: [self.SimpleNamespace(reload=lambda: reloaded.append(1))]
        self.app._refresh_tasks()
        self.assertEqual(reloaded, [1])

    def _draft_window(self, roles, templates=None):
        directory = self.gui.team_model.Directory(
            [self.gui.team_model.Person("bea", "Bea", "", ["Bea"], "owner", list(roles))], list(roles))
        draft = self.gui.team_screen.TeamDraft(directory, templates or {}, "bea")
        reloaded = []
        window = self.SimpleNamespace(winfo_exists=lambda: True, reload=lambda: reloaded.append(1), draft=draft)
        self.app._may = lambda action: True
        return window, draft, reloaded

    def _dialog_result(self, result):
        """Make the fake WorkflowDialog hand `result` to the apply callback; returns what apply answered."""
        out = []

        def dialog(parent, roles, templates, apply=None, actions=(), title=""):
            self.shown_dialog = (tuple(actions), title)
            editor = self.gui.workflow_editor.WorkflowEditor(templates)
            for op in result:
                if op["op"] == "set":
                    editor.items.setdefault(op["action"], []).append(
                        {"origin": op["old"], "name": op["name"], "rows": op["rows"], "same": op["same"],
                         "requester": op["requester"], "eco": op.get("eco", False)})
            return self.SimpleNamespace(show=lambda: out.append(apply(result, editor)))

        self.gui.workflows_dialog.WorkflowsDialog = dialog
        return out

    def test_the_workflows_window_result_is_staged_not_saved(self):
        window, draft, reloaded = self._draft_window(["Quality", "Manager"])
        out = self._dialog_result([{"op": "set", "action": "release", "name": "T1", "rows": [["Quality"]],
                                    "same": False, "requester": True, "old": None}])
        self.app.edit_workflow(window)
        self.assertEqual(out, [""])
        self.assertEqual(self.tasks, [])
        self.assertEqual([r.roles for r in draft.templates["release"]["T1"].rows], [["Quality"]])
        self.assertEqual(draft.labels, ["Workflows: Release"])
        self.assertEqual(reloaded, [1])
        self.assertEqual(self.shown_dialog, (self.gui.workflow_templates.PART_ACTIONS, "Part Workflows"))

    def test_doc_workflows_shows_only_the_documents_actions(self):
        window, draft, _ = self._draft_window(["Manager"])
        self._dialog_result([{"op": "set", "action": "release_document", "name": "T1", "rows": [["Manager"]],
                              "same": False, "requester": True, "old": None}])
        self.app.edit_workflow(window, documents=True)
        templates = self.gui.workflow_templates
        self.assertEqual(self.shown_dialog, (templates.DOCUMENT_ACTIONS, "Doc Workflows"))
        self.assertEqual(set(templates.PART_ACTIONS) | set(templates.DOCUMENT_ACTIONS), set(templates.ACTIONS))
        self.assertIn("T1", draft.templates["release_document"])

    def test_removing_a_workflow_is_staged(self):
        tpl = {"release": {"T1": self.gui.workflow_templates.Template("release", "T1", [self.gui.workflow_templates.Row(["Quality"])])}}
        window, draft, _ = self._draft_window(["Quality"], tpl)
        self._dialog_result([{"op": "remove", "action": "release", "name": "T1"}])
        self.app.edit_workflow(window)
        self.assertEqual(draft.templates, {})
        self.assertTrue(draft.dirty)

    def test_a_row_nobody_can_fill_asks_for_a_second_thought(self):
        window, draft, _ = self._draft_window(["Quality", "Empty"])
        draft.directory.people[0].roles = ["Quality"]
        out = self._dialog_result([{"op": "set", "action": "release", "name": "T1", "rows": [["Empty"]],
                                    "same": False, "requester": True, "old": None}])
        self.gui.messagebox.askyesno = lambda *a, **k: False
        self.app.edit_workflow(window)
        self.assertTrue(out[0])
        self.assertFalse(draft.dirty)


if __name__ == "__main__":
    unittest.main()
