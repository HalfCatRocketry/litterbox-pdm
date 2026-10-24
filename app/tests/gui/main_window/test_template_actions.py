"""Tests for templates in the main window (create_actions.py, team_admin.py): New Part with a template makes and
opens the model, New Drawing... asks which template and opens what it made, and Team > Templates... does what its
window chose and opens it again. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check
the wiring, not the look. Please also try the real window."""

import unittest
from types import SimpleNamespace
from unittest import mock

from litterbox.core import file_types
from litterbox.core import template_rules
from litterbox.core.part_number import PN
from litterbox.gui.logic.action_rules import ActionPlan
from litterbox.parts.part_status import PartStatus
from litterbox.team import team_identity
from tests.support.gui_fakes import FakeBox, fake_jobs, load_gui_with_fakes, replace

PART = PN("HCR", 7, 1)
TEMPLATES = template_rules.added(template_rules.added([], "HCR A.drwdot"), "HCR B.drwdot")


class TemplateActions(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        App = self.gui.app.App
        app = App.__new__(App)
        app.rows_by_pn = {PART: PartStatus(PART, "Bracket", "in_work", "Checked out by you", "mine",
                                           files=["cad/HCR-00007-001_A.SLDPRT"])}
        app.jobs = fake_jobs()
        app.identity = team_identity.Identity(team_identity.LEGACY)
        app.org = "HCR"
        app.repo = lambda: "C:/vault"
        app.queue = SimpleNamespace(put=lambda item: None)
        app.search = SimpleNamespace(delete=lambda *a: None)
        self.said, self.tasks, self.opened = [], [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app._plan = lambda action: ActionPlan([PART])
        app._open_path = self.opened.append
        app.run_task = lambda work, done, on_success=None, **kwargs: self.tasks.append((work, on_success, kwargs))
        app._may = lambda action: True
        self.app = app
        actions = self.gui.create_actions
        replace(self, actions.record_store, "load",
                lambda repo, pn: SimpleNamespace(pn=pn, revision="A", project="", is_document=False, uses_cad=True))
        replace(self, actions.from_template, "choices", lambda repo, pn, kind: list(TEMPLATES))

    def run_tasks(self):
        for work, on_success, _kwargs in self.tasks:
            result = work()
            if on_success:
                on_success(result)

    def test_new_drawing_asks_which_template_then_opens_what_it_made(self):
        asked, made = [], []

        class Choice:
            def __init__(self, parent, title, file_name, templates, note=""):
                asked.append((title, file_name, [t.file for t in templates]))

            def show(self):
                return "HCR B.drwdot"

        replace(self, self.gui.template_choice_dialog, "TemplateChoiceDialog", Choice)
        replace(self, self.gui.create_actions.from_template, "make",
                lambda repo, pn, file, log=None: made.append((pn, file)) or "cad/HCR-00007-001_A.SLDDRW")
        self.app.new_drawing()
        self.assertEqual(asked, [("New Drawing", "HCR-00007-001_A.SLDDRW", ["HCR A.drwdot", "HCR B.drwdot"])])
        self.run_tasks()
        self.assertEqual(made, [(PART, "HCR B.drwdot")])
        self.assertEqual(self.opened, ["cad/HCR-00007-001_A.SLDDRW"])

    def test_new_drawing_says_why_not_without_asking(self):
        self.app.rows_by_pn[PART].files.append("cad/HCR-00007-001_A.SLDDRW")
        replace(self, self.gui.template_choice_dialog, "TemplateChoiceDialog", None)        # never opened
        self.app.new_drawing()
        self.assertIn("has a drawing already", self.said[-1])
        replace(self, self.gui.create_actions.from_template, "choices", lambda repo, pn, kind: [])
        self.app.rows_by_pn[PART].files[:] = []
        self.app.new_model()
        self.assertIn("No part templates", self.said[-1])

    def test_new_part_with_a_template_opens_the_model_made(self):
        actions = self.gui.create_actions
        request = {"name": "Bracket", "description": "", "base": None, "variant": None, "project": None,
                   "kind": "part", "noncad": False, "template": "HCR part.prtdot"}
        replace(self, actions.new_part_dialog, "NewPartDialog",
                lambda parent, repo, org, kind: SimpleNamespace(show=lambda: request))
        replace(self, actions.create, "new_part", lambda *a, **kw: PART)
        replace(self, actions.checkout, "checkout", lambda repo, pn: None)
        replace(self, actions.from_template, "make", lambda repo, pn, file, log=None: "cad/HCR-00007-001_A.SLDPRT")
        replace(self, actions.filename_dialog, "FilenameDialog", None)          # not needed: the file is made
        with mock.patch("pathlib.Path.is_dir", return_value=True):
            self.app.new_part()
        self.run_tasks()
        self.assertEqual(self.opened, ["cad/HCR-00007-001_A.SLDPRT"])

    def test_team_templates_does_what_was_chosen_and_opens_again(self):
        admin = self.gui.team_admin
        shown, done = [], []
        answers = [("default", "HCR B.drwdot"), None]

        class Dialog:
            def __init__(self, window, templates, owners, may_change, project=""):
                shown.append((len(templates), owners, may_change(""), project))

            def show(self):
                return answers.pop(0)

        replace(self, admin.templates_dialog, "TemplatesDialog", Dialog)
        replace(self, admin.config, "apply", lambda repo: None)
        replace(self, admin.config, "get_projects", lambda repo: [])
        replace(self, admin.template_store, "load", lambda repo: list(TEMPLATES))
        replace(self, admin.project_access, "usable_here", lambda repo, projects: [])
        replace(self, admin.template_admin, "make_default", lambda repo, file: done.append(file))
        self.app.manage_templates("window")
        self.run_tasks()
        self.assertEqual(done, ["HCR B.drwdot"])
        self.assertEqual(shown, [(2, [], (True, ""), ""), (2, [], (True, ""), "")])     # opened again after
        self.assertEqual(self.said[-1], "Template HCR B is now the default")

    def test_a_template_choice_reads_well(self):
        from litterbox.gui.logic import template_text
        labels = list(template_text.choice_map(template_rules.choices(TEMPLATES, file_types.DRAWING)))
        self.assertEqual(labels, ["HCR A  (org drawing default)", "HCR B  (org drawing)", template_text.NONE])


if __name__ == "__main__":
    unittest.main()
