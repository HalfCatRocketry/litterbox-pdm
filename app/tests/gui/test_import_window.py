"""
Smoke test for the Import window in litterbox_gui.py, with the screen replaced by stand-ins.

No real window is opened (so this runs anywhere, even without tkinter): customtkinter and tkinter
are replaced by simple fakes, a fake table remembers its rows, and the test plays the user by calling
the same functions the buttons call. It checks the wiring - the right things are shown, buttons call the
right session steps, errors reach the user - not how the window looks. Please also try the real window.

Run from the app folder with:  python -m unittest discover -s tests -t . -v
"""

import importlib.util
import queue
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.support.import_fixture import ImportFixture
from tests.support.vault_fixture import SKIP_ON_WINDOWS

from litterbox.importing import session as import_session
from litterbox.importing import importer
from litterbox.records import registry
from litterbox.user import settings


REAL_SESSION = import_session.ImportSession


class Anything:
    """A widget that accepts any call and remembers nothing."""

    def __init__(self, *args, **kwargs):
        self.options = dict(kwargs)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return mock.MagicMock()

    def configure(self, *args, **kwargs):
        self.options.update(kwargs)

    def cget(self, key):
        return self.options.get(key)


class FakeVar:
    def __init__(self, value=None, **kwargs):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeTree(Anything):
    def __init__(self, parent=None, columns=(), **kwargs):
        super().__init__()
        self.columns, self.rows, self.chosen = list(columns), {}, ()

    def insert(self, parent, index, iid=None, tags=(), values=()):
        self.rows[iid] = {"tags": tags, "values": list(values)}

    def get_children(self):
        return tuple(self.rows)

    def delete(self, *ids):
        for i in ids:
            self.rows.pop(i, None)

    def exists(self, iid):
        return iid in self.rows

    def item(self, iid, option=None, **changes):
        if "tags" in changes:
            self.rows[iid]["tags"] = changes["tags"]
        return tuple(self.rows[iid]["tags"]) if option == "tags" else None

    def selection(self):
        return self.chosen

    def selection_set(self, *ids):
        self.chosen = ids

    def set(self, iid, column, value=None):
        if value is not None:
            self.rows[iid]["values"][self.columns.index(column)] = value
        return self.rows[iid]["values"][self.columns.index(column)]


class FakeBox:
    def __init__(self):
        self.calls = []
        self.answer = True              # what Yes/No questions are answered with

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            return self.answer if name in ("askyesno", "askokcancel") else None
        return call


def fake_jobs(busy=False, pending=None):
    """Stands in for the window's job queue in tests that build the window without running its __init__."""
    return types.SimpleNamespace(active=lambda: busy, working=lambda: busy, pending_parts=lambda: dict(pending or {}))


def load_gui_with_fakes(box):
    ctk = types.ModuleType("customtkinter")
    ctk.__getattr__ = lambda name: Anything
    tk = types.ModuleType("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    tk.StringVar = tk.BooleanVar = FakeVar
    tk.__getattr__ = lambda name: Anything
    ttk = types.ModuleType("tkinter.ttk")
    ttk.Treeview = FakeTree
    ttk.Style = Anything
    dialogs = types.ModuleType("tkinter.filedialog")
    dialogs.askdirectory = lambda **k: ""
    dialogs.askopenfilename = lambda **k: ""
    mbox = types.ModuleType("tkinter.messagebox")
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
        setattr(mbox, name, getattr(box, name))
    tk.filedialog, tk.messagebox, tk.ttk = dialogs, mbox, ttk
    fakes = {"customtkinter": ctk, "tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": dialogs,
             "tkinter.messagebox": mbox}
    app = Path(__file__).resolve().parents[2] / "litterbox" / "gui" / "litterbox_gui.py"
    with mock.patch.dict(sys.modules, fakes):
        spec = importlib.util.spec_from_file_location("litterbox_gui_under_test", app)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def replace(test, obj, name, value):
    """Swap an attribute for this one test only. The program's modules are shared by every test in a run, so a
    swap that isn't undone would break whichever test runs next."""
    original = getattr(obj, name)
    test.addCleanup(setattr, obj, name, original)
    setattr(obj, name, value)


class FakeParent:
    def winfo_rootx(self): return 0
    def winfo_rooty(self): return 0
    def winfo_width(self): return 1200
    def winfo_height(self): return 800


class FakeWindow:
    """Just enough of a window to watch the fade: it records opacity changes and queued timers."""

    def __init__(self):
        self.alpha, self.alphas, self.timers, self.destroyed = 1.0, [], [], False

    def attributes(self, name, value):
        self.alpha = value
        self.alphas.append(value)

    def after(self, ms, fn):
        self.timers.append(fn)

    def bind(self, *args, **kwargs):
        pass

    def winfo_exists(self):
        return not self.destroyed

    def protocol(self, name, handler):
        self.protocols = getattr(self, "protocols", {})
        self.protocols[name] = handler

    def iconbitmap(self, *args, **kwargs):
        self.icon_calls = getattr(self, "icon_calls", 0) + 1

    def destroy(self):
        self.destroyed = True

    def run_timers(self):
        while self.timers and not self.destroyed:
            self.timers.pop(0)()


class TeamWiring(unittest.TestCase):
    """Read-only mode in the window: who may press what."""

    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.team import people
        from litterbox.parts.engine import PartStatus
        from litterbox.core.pn import PN
        self.people = people
        self.pn = PN("HCR", 7, 1)
        row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=["cad/HCR-00007-001_A.SLDPRT"],
                         revisions={"A": ["cad/HCR-00007-001_A.SLDPRT"]})
        app = self.gui.App.__new__(self.gui.App)
        app.rows_by_pn = {self.pn: row}
        app._selected_pns = lambda action=None: [self.pn]
        self.said = []
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        self.app = app

    def test_legacy_vaults_allow_everything(self):
        self.app.identity = self.people.Identity(self.people.LEGACY)
        self.assertIsNotNone(self.app._plan("checkout"))

    def test_someone_not_listed_can_look_but_every_change_is_refused_with_the_reason(self):
        self.app.identity = self.people.Identity(self.people.NOT_LISTED, "stranger")
        for action in ("checkout", "checkin", "release", "revise", "edit", "void"):
            self.said.clear()
            self.assertIsNone(self.app._plan(action), action)
            self.assertIn("not on this vault's team list", self.said[0][0])
        for action in ("open", "open_drawing", "references"):
            self.assertIsNotNone(self.app._plan(action), action)

    def test_new_part_and_import_are_refused_too(self):
        self.app.identity = self.people.Identity(self.people.UNVERIFIED)
        self.app.jobs = fake_jobs()
        self.app.new_part()
        self.app.import_cad()
        self.assertEqual(len(self.said), 2)
        self.assertTrue(all(tone == "warn" for _t, tone in self.said))

    def test_a_member_may_work_but_not_manage_people(self):
        person = self.people.Person("m", "M")
        self.app.identity = self.people.Identity(self.people.OK, "m", person)
        self.assertIsNotNone(self.app._plan("checkout"))
        self.assertFalse(self.app._may("manage_people"))
        self.assertIn("Only an Admin", self.said[-1][0])


class ReleaseButtonTests(unittest.TestCase):
    """Buttons act when the mouse button is released over them, not when it is pressed."""

    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.clicks = []
        base = self.gui.ReleaseButton.__mro__[1]
        base._clicked = lambda button, event=None: self.clicks.append(event)
        self.addCleanup(lambda: delattr(base, "_clicked"))
        button = self.gui.ReleaseButton()
        button._state = "normal"
        button.winfo_rootx = lambda: 100
        button.winfo_rooty = lambda: 50
        button.winfo_width = lambda: 80
        button.winfo_height = lambda: 30
        self.button = button

    @staticmethod
    def at(x, y):
        from types import SimpleNamespace
        return SimpleNamespace(x_root=x, y_root=y)

    def test_pressing_alone_does_nothing(self):
        self.button._clicked(self.at(110, 60))
        self.assertEqual(self.clicks, [])

    def test_press_then_release_over_the_button_clicks_once(self):
        self.button._clicked(self.at(110, 60))
        self.button._released(self.at(120, 65))
        self.button._released(self.at(120, 65))              # a second release without a press does nothing
        self.assertEqual(len(self.clicks), 1)

    def test_releasing_away_from_the_button_cancels_the_click(self):
        self.button._clicked(self.at(110, 60))
        self.button._released(self.at(300, 65))
        self.assertEqual(self.clicks, [])
        self.button._released(self.at(120, 65))              # and the press is forgotten
        self.assertEqual(self.clicks, [])

    def test_a_missing_release_event_is_caught_by_the_mouse_check(self):
        state = {"down": True}
        self.gui.left_button_down = lambda: state["down"]
        self.button.winfo_pointerxy = lambda: (120, 65)
        self.button._clicked(self.at(110, 60))
        self.button._watch_mouse()                              # still held: nothing yet
        self.assertEqual(self.clicks, [])
        state["down"] = False
        self.button._watch_mouse()                              # let go, and Tk never sent the event
        self.assertEqual(len(self.clicks), 1)
        self.button._released(self.at(120, 65))                 # a late event doesn't click twice
        self.button._watch_mouse()
        self.assertEqual(len(self.clicks), 1)

    def test_mouse_check_cancels_when_let_go_off_the_button(self):
        self.gui.left_button_down = lambda: False
        self.button.winfo_pointerxy = lambda: (500, 500)
        self.button._clicked(self.at(110, 60))
        self.button._watch_mouse()
        self.assertEqual(self.clicks, [])

    def test_windows_saying_the_pointer_is_over_the_button_counts_even_if_tk_disagrees(self):
        # The edge-click bug: Tk's coordinates were off, so only the middle of a button worked.
        self.gui.pointer_inside = lambda widget: True
        self.button._clicked(self.at(110, 60))
        self.button._released(self.at(400, 400))
        self.assertEqual(len(self.clicks), 1)

    def test_a_click_at_the_very_edge_counts(self):
        self.gui.pointer_inside = lambda widget: None            # this system can't say: Tk's numbers decide
        for x, y in ((100, 50), (179, 79), (98, 49), (182, 82)):      # corners, and a few pixels of slack
            self.clicks.clear()
            self.button._clicked(self.at(x, y))
            self.button._released(self.at(x, y))
            self.assertEqual(len(self.clicks), 1, (x, y))

    def test_far_from_the_button_is_still_a_cancelled_click(self):
        self.gui.pointer_inside = lambda widget: False
        self.button._clicked(self.at(110, 60))
        self.button._released(self.at(190, 60))                  # 10 px past the right edge
        self.assertEqual(self.clicks, [])

    def test_a_disabled_button_never_arms(self):
        self.button._state = "disabled"
        self.button._clicked(self.at(110, 60))
        self.button._released(self.at(120, 65))
        self.assertEqual(self.clicks, [])


class CreateVaultWiring(unittest.TestCase):
    """The Create new vault... entry in the org menu."""

    def setUp(self):
        from types import SimpleNamespace
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        app = self.gui.App.__new__(self.gui.App)
        self.tasks, self.switched = [], []
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, done, on_success))
        app.switch_org = self.switched.append
        app._reload_org_menu = lambda: None
        app.settings = {}
        self.app = app
        self.dialog_result = ("HCR", "C:\\Litterbox\\hcr", 1, 5, 3)
        self.gui.OrgDialog = lambda *a, **k: SimpleNamespace(show=lambda: self.dialog_result)
        self.plan = SimpleNamespace(ok=True, problems=[], warnings=[], org="HCR")
        replace(self, self.gui.init_vault, "plan", lambda *a, **k: self.plan)
        replace(self, self.gui.settings, "save", lambda data: None)

    def shown(self, name):
        return [call for call in self.box.calls if call[0] == name]

    def test_choosing_the_menu_entry_starts_it(self):
        started = []
        self.app.create_vault = lambda: started.append(True)
        self.app.on_org_chosen(self.gui.logic.CREATE_VAULT)
        self.assertEqual(started, [True])

    def test_not_having_cloned_it_yet_stops_at_the_first_question(self):
        self.box.answer = False
        self.app.create_vault()
        self.assertEqual(self.tasks, [])

    def test_problems_are_shown_and_nothing_runs(self):
        self.plan.ok, self.plan.problems = False, ["No remote."]
        self.app.create_vault()
        self.assertEqual(self.tasks, [])
        self.assertIn("No remote.", self.shown("showerror")[0][1][1])

    def test_a_declined_warning_stops_it(self):
        self.plan.warnings = ["Only 999 parts."]
        answers = iter([True, False])
        self.gui.messagebox.askyesno = lambda *a, **k: next(answers)
        self.app.create_vault()
        self.assertEqual(self.tasks, [])

    def test_creating_runs_in_the_background_and_then_opens_the_new_org(self):
        from types import SimpleNamespace
        calls = []
        replace(self, self.gui.init_vault, "create", lambda *a, **k: calls.append(a) or "made")
        self.app.create_vault()
        work, done, on_success = self.tasks[0]
        self.assertEqual(work(), "made")
        self.assertEqual(calls[0][:5], ("C:\\Litterbox\\hcr", "HCR", 1, 5, 3))
        on_success(SimpleNamespace(org="HCR", pushed=True, owner=None, team_error="", warnings=[]))
        self.assertEqual(self.switched, ["HCR"])
        self.assertEqual(self.app.settings["orgs"], {"HCR": "C:\\Litterbox\\hcr"})
        self.assertTrue(self.shown("showinfo"))


class WorkflowWiring(unittest.TestCase):
    """The window side of workflows: starting one, My Tasks, and the Workflows window."""

    def setUp(self):
        from types import SimpleNamespace
        self.SimpleNamespace = SimpleNamespace
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.wf = self.gui.workflow
        app = self.gui.App.__new__(self.gui.App)
        self.tasks, self.said = [], []
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, done, on_success))
        app._say = lambda text, tone="normal": self.said.append(text)
        app.repo = lambda: "C:/vault"
        app.rows, app.rows_by_pn = [], {}
        directory = self.gui.people.Directory(
            [self.gui.people.Person("alex", "Alex", "", ["Alex"], "owner", ["Responsible Engineer"]),
             self.gui.people.Person("bea", "Bea", "", ["Bea"], "member", ["Quality"])],
            ["Responsible Engineer", "Quality"])
        self.directory = directory
        app.identity = SimpleNamespace(state="ok", directory=directory, person=directory.get("alex"))
        app.note = ""
        self.asked = []
        app._ask = lambda text, title: self.asked.append((text, title)) or self.answer
        self.answer = ""
        self.app = app
        self.templates = {"T1": self.wf.Template("release", "T1", [self.wf.Row(["Quality"])])}
        replace(self, self.wf, "templates_for", lambda repo, action: self.templates)

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
            def __init__(inner, parent, action, parts, templates, directory, my_id):
                seen.append((action, parts, list(templates), my_id))

            def show(inner):
                return {"template": "T1", "assignments": ["bea"], "extras": [("Quality", "bea")], "reason": ""}

        self.gui.WorkflowRequestDialog = Dialog
        calls = []
        replace(self, self.wf, "request", lambda *a: calls.append(a) or "id")
        self.app.release()
        self.assertEqual(seen, [("release", [("HCR-00001-001", "Upright"), ("HCR-00002-001", "Upright")], ["T1"],
                                 "alex")])
        work, done, _ = self.tasks.pop()
        work()
        self.assertEqual(calls, [("C:/vault", ["HCR-00001-001", "HCR-00002-001"], "release", "T1", ["bea"],
                                  [("Quality", "bea")], "")])
        self.assertIn("2 parts", done)

    def test_cancelling_the_workflow_window_does_nothing(self):
        self.targets("HCR-00001-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok")}
        self.gui.WorkflowRequestDialog = lambda *a: self.SimpleNamespace(show=lambda: None)
        self.app.release()
        self.assertEqual(self.tasks, [])

    def test_reopen_void_and_make_cots_use_the_window_too(self):
        for action, method in (("reopen", "reopen"), ("void", "void"), ("make_cots", "make_cots")):
            with self.subTest(action=action):
                self.targets("HCR-00001-001")
                self.app.rows_by_pn = {"HCR-00001-001": self.row("ok")}
                opened = []
                self.gui.WorkflowRequestDialog = lambda parent, act, *a: opened.append(act) or self.SimpleNamespace(
                    show=lambda: None)
                getattr(self.app, method)()
                self.assertEqual(opened, [action])

    def plan(self, n, ok=True, problems=()):
        return self.SimpleNamespace(pn=f"HCR-0000{n}-001", name="Upright", files=["cad/a.SLDPRT"], warnings=[],
                                    problems=list(problems), ok=ok)

    def test_without_a_workflow_release_works_as_before(self):
        self.templates = {}
        released = []
        replace(self, self.gui.engine, "release_many", lambda repo, pns: released.append(pns) or ([], []))
        self.app._confirm_release("C:/vault", [self.plan(1)])
        self.tasks.pop()[0]()
        self.assertEqual(released, [["HCR-00001-001"]])

    def test_without_a_workflow_several_parts_are_released_together(self):
        self.templates = {}
        self.targets("HCR-00001-001", "HCR-00002-001")
        self.app.rows_by_pn = {"HCR-00001-001": self.row("ok"), "HCR-00002-001": self.row("ok", pn="HCR-00002-001")}
        looked = []
        replace(self, self.gui.engine, "release_plans", lambda repo, pns: looked.append(pns) or "plans")
        self.app.release()
        work, _done, on_success = self.tasks.pop()
        self.assertEqual(work(), "plans")
        self.assertEqual(looked, [["HCR-00001-001", "HCR-00002-001"]])

        released = []
        replace(self, self.gui.engine, "release_many", lambda repo, pns: released.append(pns) or ([], []))
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
            replace(self, self.gui.engine, name, lambda repo, pns, reason, name=name: got.append((name, pns, reason))
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
        replace(self, self.wf, "complete_many", lambda repo, pns: done.append(pns))
        self.app.release()
        self.tasks.pop()[0]()
        self.assertEqual(done, [["HCR-00001-001"]])

    def test_approving_passes_the_comment_and_reports_a_failure(self):
        self.answer = "Looks right"
        seen = []
        replace(self, self.wf, "sign_off", lambda repo, pns, comment: seen.append((pns, comment)) or "result")
        self.app.task_sign(self.task())
        work, done, on_success = self.tasks.pop()
        self.assertEqual(work(), "result")
        self.assertEqual(seen, [(["HCR-00001-001"], "Looks right")])
        on_success(self.SimpleNamespace(completed=[], errors={"HCR-00001-001": "offline"}))
        self.assertIn("offline", self.shown("showwarning")[0][1][1])
        on_success(self.SimpleNamespace(completed=["HCR-00001-001"], errors={}))
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
        replace(self, self.wf, "reject", lambda repo, pns, reason: seen.append((pns, reason)))
        self.app.task_reject(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], "Missing tolerance")])

    def test_withdrawing_asks_first(self):
        self.box.answer = False
        self.app.task_withdraw(self.task())
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        gone = []
        replace(self, self.wf, "withdraw", lambda repo, pns: gone.append(pns))
        self.app.task_withdraw(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(gone, [["HCR-00001-001"]])

    def test_completing_asks_first(self):
        self.box.answer = False
        self.app.task_complete(self.task())
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        done = []
        replace(self, self.wf, "complete_many", lambda repo, pns: done.append(pns))
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
        replace(self, self.wf, "override", lambda repo, pns, reason, action=None: seen.append((pns, reason, action)))
        self.app.task_override(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], "Quality is away", "release")])

    def test_changing_a_signer(self):
        self.gui.ReassignDialog = lambda parent, task, directory: self.SimpleNamespace(show=lambda: (0, "alex"))
        seen = []
        replace(self, self.wf, "reassign", lambda repo, pns, slot, person: seen.append((pns, slot, person)))
        self.app.task_reassign(self.task())
        self.tasks.pop()[0]()
        self.assertEqual(seen, [(["HCR-00001-001"], 0, "alex")])
        self.gui.ReassignDialog = lambda *a: self.SimpleNamespace(show=lambda: None)
        self.app.task_reassign(self.task())
        self.assertEqual(self.tasks, [])

    def test_the_button_shows_how_many_things_need_you(self):
        shown = []
        self.app.tasks_button = self.SimpleNamespace(configure=lambda **k: shown.append(k["text"]))
        self.app._task_windows = lambda: []
        self.app.identity = self.SimpleNamespace(state="ok", directory=self.directory,
                                                 person=self.directory.get("bea"))
        self.app.rows = [self.row("pending", self.pending())]
        self.app._refresh_tasks()
        self.assertEqual(shown[-1], "My Tasks (1)")
        self.app.rows = []
        self.app._refresh_tasks()
        self.assertEqual(shown[-1], "My Tasks")

    def _draft_window(self, roles, templates=None):
        directory = self.gui.people.Directory(
            [self.gui.people.Person("bea", "Bea", "", ["Bea"], "owner", list(roles))], list(roles))
        draft = self.gui.TeamDraft(directory, templates or {}, "bea")
        reloaded = []
        window = self.SimpleNamespace(winfo_exists=lambda: True, reload=lambda: reloaded.append(1), draft=draft)
        self.app._may = lambda action: True
        return window, draft, reloaded

    def _dialog_result(self, result):
        """Make the fake WorkflowDialog hand `result` to the apply callback; returns what apply answered."""
        out = []

        def dialog(parent, roles, templates, apply=None):
            editor = self.gui.logic.WorkflowEditor(templates)
            for op in result:
                if op["op"] == "set":
                    editor.items.setdefault(op["action"], []).append(
                        {"origin": op["old"], "name": op["name"], "rows": op["rows"], "same": op["same"],
                         "requester": op["requester"]})
            return self.SimpleNamespace(show=lambda: out.append(apply(result, editor)))

        self.gui.WorkflowsDialog = dialog
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

    def test_removing_a_workflow_is_staged(self):
        tpl = {"release": {"T1": self.wf.Template("release", "T1", [self.wf.Row(["Quality"])])}}
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


class TickAndSaveWiring(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.core.pn import PN
        self.PN = PN
        app = self.gui.App.__new__(self.gui.App)
        app.ticked = set()
        app.tree = SortableFakeTree(["tick", "pn"])
        for pn in ("HCR-00001-001", "HCR-00002-001", "HCR-00003-001"):
            app.tree.insert("", "end", iid=pn, values=["\u2610", pn])
        self.said = []
        app._say = lambda text, tone="normal": self.said.append(text)
        self.app = app

    def test_ticking_leaves_the_highlight_alone(self):
        self.app.tree.selection_set("HCR-00003-001")
        self.app._set_ticks(["HCR-00001-001", "HCR-00002-001"], True)
        self.assertEqual(self.app.tree.rows["HCR-00001-001"]["values"][0], "\u2611")
        self.assertEqual(self.app.tree.selection(), ("HCR-00003-001",) if isinstance(self.app.tree.selection(), tuple)
                         else ["HCR-00003-001"])

    def test_changing_actions_use_the_ticks_and_looking_uses_the_highlight(self):
        self.app._set_ticks(["HCR-00001-001", "HCR-00002-001"], True)
        self.app.tree.selection_set("HCR-00003-001")
        got = [str(p) for p in self.app._selected_pns("checkout")]
        self.assertEqual(got, ["HCR-00001-001", "HCR-00002-001"])
        self.assertEqual(self.app._selected_pns("release") and [str(p) for p in self.app._selected_pns("release")],
                         ["HCR-00001-001", "HCR-00002-001"])
        self.assertEqual([str(p) for p in self.app._selected_pns("open")], ["HCR-00003-001"])

    def test_a_tick_on_a_part_that_left_the_list_is_ignored(self):
        self.app._set_ticks(["HCR-00001-001"], True)
        self.app.tree.delete("HCR-00001-001")
        self.assertEqual(self.app._selected_pns("checkout"), [])

    def test_ticked_rows_get_the_ticked_tag_and_keep_their_colour(self):
        self.app.tree.rows["HCR-00001-001"]["tags"] = ("mine",)
        self.app._set_ticks(["HCR-00001-001"], True)
        self.assertEqual(self.app.tree.item("HCR-00001-001", "tags"), ("mine", "ticked"))
        self.app._set_ticks(["HCR-00001-001"], False)
        self.assertEqual(self.app.tree.item("HCR-00001-001", "tags"), ("mine",))

    def _click(self, iid, shift=False):
        tree = self.app.tree
        tree.identify_region = lambda x, y: "cell"
        tree.identify_column = lambda x: "#1"
        tree.identify_row = lambda y: iid
        return self.app._on_tree_click(self.SimpleNamespace(x=1, y=1, state=1 if shift else 0))

    def test_shift_click_ticks_everything_between(self):
        from types import SimpleNamespace
        self.SimpleNamespace = SimpleNamespace
        self._click("HCR-00001-001")
        self._click("HCR-00003-001", shift=True)
        self.assertEqual(self.app.ticked, {"HCR-00001-001", "HCR-00002-001", "HCR-00003-001"})

    def test_shift_click_after_an_untick_unticks_the_range(self):
        from types import SimpleNamespace
        self.SimpleNamespace = SimpleNamespace
        self.app._set_ticks(["HCR-00001-001", "HCR-00002-001", "HCR-00003-001"], True)
        self._click("HCR-00001-001")                    # unticks the first
        self._click("HCR-00003-001", shift=True)        # and the range to the last
        self.assertEqual(self.app.ticked, set())

    def _buttons(self):
        from types import SimpleNamespace
        from litterbox.parts.engine import PartStatus
        app = self.app
        app.jobs = fake_jobs()
        app.rows_by_pn = {self.PN.parse if False else None: None}
        pns = {n: self.PN("HCR", n, 1) for n in (1, 2, 3)}
        kinds = {1: "ok", 2: "mine", 3: "released"}
        app.rows_by_pn = {pns[n]: PartStatus(pns[n], "x", "in_work", "s", kinds[n]) for n in pns}
        app.action_buttons = {text: SimpleNamespace(state=None, configure=lambda state, b=None: None)
                              for text in self.gui.logic.BUTTON_ACTIONS}
        log = {}
        for text in app.action_buttons:
            app.action_buttons[text].configure = lambda state, text=text: log.__setitem__(text, state)
        app.deselect_button = SimpleNamespace(configure=lambda state: log.__setitem__("Deselect All", state))
        return log

    def test_buttons_follow_the_selection(self):
        log = self._buttons()
        self.app._set_ticks(["HCR-00001-001"], True)
        self.assertEqual(log["Check Out"], "normal")
        self.assertEqual(log["Check In"], "disabled")
        self.assertEqual(log["Deselect All"], "normal")
        self.app._set_ticks(["HCR-00002-001"], True)
        self.assertEqual(log["Check Out"], "disabled")            # one of the two is already checked out
        self.app._set_ticks(["HCR-00001-001", "HCR-00002-001"], False)
        self.assertEqual(log["Check Out"], "disabled")
        self.assertEqual(log["Deselect All"], "disabled")

    def test_buttons_stay_usable_while_other_parts_have_jobs(self):
        log = self._buttons()
        self.app._set_ticks(["HCR-00001-001"], True)
        self.app.jobs = fake_jobs(busy=True, pending={"HCR-00002-001": "Checking in 1 part"})
        self.app._update_buttons()
        self.assertEqual(log["Check Out"], "normal")                # part 1 has nothing going on

    def test_a_part_with_a_job_in_progress_cannot_be_acted_on(self):
        log = self._buttons()
        self.app._set_ticks(["HCR-00002-001"], True)
        self.app.jobs = fake_jobs(busy=True, pending={"HCR-00002-001": "Checking in 1 part"})
        self.app._update_buttons()
        for text in ("Check In", "Save Progress", "Undo Checkout", "Edit Details", "Void"):
            self.assertEqual(log[text], "disabled", text)
        plan = self.app._plan("undo")
        self.assertIsNone(plan)
        self.assertIn("busy: checking in 1 part", self.said[-1][0] if isinstance(self.said[-1], tuple) else self.said[-1])

    def test_deselect_all_clears_every_box_and_the_highlight(self):
        self._buttons()
        self.app._set_ticks(["HCR-00001-001", "HCR-00002-001"], True)
        self.app.tree.selection_set("HCR-00003-001")
        self.app._deselect_all()
        self.assertEqual(self.app.ticked, set())
        self.assertEqual(tuple(self.app.tree.selection()), ())
        self.assertEqual(self.app.tree.rows["HCR-00001-001"]["values"][0], "\u2610")

    def test_shift_click_in_the_references_window(self):
        from types import SimpleNamespace
        window = self.gui.ReferencesWindow.__new__(self.gui.ReferencesWindow)
        window.busy, window.last_click = False, {}
        tree = SortableFakeTree(["tick", "pn"])
        for n, mark in enumerate(("\u2610", "\u2610", "", "\u2610"), 1):         # row 3 can't be changed
            tree.insert("", "end", iid=str(n), values=[mark, str(n)])
        tree.identify_region = lambda x, y: "cell"
        tree.identify_column = lambda x: "#1"
        def click(iid, shift=False):
            tree.identify_row = lambda y: iid
            window._click(tree, SimpleNamespace(x=1, y=1, state=1 if shift else 0))
        click("1")
        click("4", shift=True)
        self.assertEqual([tree.set(i, "tick") for i in "1234"], ["\u2611", "\u2611", "", "\u2611"])
        click("4")
        click("1", shift=True)
        self.assertEqual([tree.set(i, "tick") for i in "1234"], ["\u2610", "\u2610", "", "\u2610"])

    def test_tick_all_then_none(self):
        self.app._toggle_all_ticks()
        self.assertEqual(len(self.app.ticked), 3)
        self.app._toggle_all_ticks()
        self.assertEqual(self.app.ticked, set())

    def test_nothing_to_save_is_information_not_an_error(self):
        shown = []
        self.gui.messagebox.showinfo = lambda *a, **k: shown.append(("info", k.get("parent")))
        self.gui.messagebox.showerror = lambda *a, **k: shown.append(("error", None))
        app = self.app
        app._sync_busy = lambda: None
        app.jobs = self.gui.jobs.JobQueue(deliver=lambda outcome: None)
        app._popup_parent = lambda: "TEAM"
        app._log = lambda text: None
        app.note = "x"
        job = self.gui.jobs.Job("Checking in", lambda: None, token=("", None, False, False))
        app._finish(self.gui.jobs.Outcome(job, error=self.gui.engine.NothingToSaveError("Nothing was different.")))
        self.assertEqual(shown, [("info", "TEAM")])
        self.assertEqual(app.jobs.errors(), [])

    def test_a_real_error_turns_the_banner_red_without_a_popup(self):
        shown = []
        self.gui.messagebox.showerror = lambda *a, **k: shown.append("error")
        app = self.app
        app._sync_busy = lambda: None
        app.jobs = self.gui.jobs.JobQueue(deliver=lambda outcome: None)
        app._log = lambda text: None
        app.note = "x"
        job = self.gui.jobs.Job("Checking in 2 parts", lambda: None, token=("", None, False, False))
        app._finish(self.gui.jobs.Outcome(job, error="fatal: unable to access 'https://x': Could not resolve host"))
        self.assertEqual(shown, [])
        (note,) = app.jobs.errors()
        self.assertEqual(note.label, "Checking in 2 parts")
        self.assertIn("internet connection", note.advice)
        self.assertEqual(app.jobs.banner().kind, "error")


class UpdateWiring(unittest.TestCase):
    """The window side of updates: asking, downloading, handing over to the installer."""

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.updater = self.gui.updater             # the copy the window itself uses
        self.update = self.updater.Update("0.2.0", "Fixes things.", "Litterbox-Setup-0.2.0.exe", "https://x", "a" * 64, 5)
        app = self.gui.App.__new__(self.gui.App)
        self.said, self.tasks, self.scheduled = [], [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False, **_kw: self.tasks.append(
            (work, on_success))
        app.after = lambda ms, fn=None: self.scheduled.append((ms, fn))
        app.queue = __import__("queue").Queue()
        app.settings = {}
        app.destroy = self.destroy = lambda: None
        self.app = app

    def test_nothing_happens_without_an_update(self):
        self.app._offer_update(None)
        self.assertEqual(self.box.calls, [])

    def test_yes_downloads_and_no_does_not(self):
        self.box.answer = False
        self.app._offer_update(self.update)
        self.assertEqual(self.tasks, [])
        self.box.answer = True
        self.app._offer_update(self.update)
        self.assertEqual(len(self.tasks), 1)
        question = self.box.calls[-1][1][1]
        self.assertIn("0.2.0", question)
        self.assertIn("Fixes things.", question)

    def test_a_download_problem_becomes_a_plain_error(self):
        from litterbox.parts.engine import LitterboxError
        self.app.install_update(self.update)
        work, _ = self.tasks[0]
        original = self.updater.download
        self.updater.download = lambda update: (_ for _ in ()).throw(self.updater.UpdateError("did not match"))
        try:
            with self.assertRaisesRegex(LitterboxError, "did not match"):
                work()
        finally:
            self.updater.download = original

    def test_after_downloading_the_installer_starts_and_litterbox_closes(self):
        started = []
        original = self.updater.launch_installer
        self.updater.launch_installer = lambda path: started.append(path)
        try:
            self.app._run_installer("C:/tmp/Setup.exe")
        finally:
            self.updater.launch_installer = original
        self.assertEqual(started, ["C:/tmp/Setup.exe"])
        self.assertIs(self.scheduled[-1][1], self.destroy)

    def test_if_the_installer_cannot_start_litterbox_stays_open(self):
        original = self.updater.launch_installer
        self.updater.launch_installer = lambda path: (_ for _ in ()).throw(self.updater.UpdateError("blocked"))
        try:
            self.app._run_installer("C:/tmp/Setup.exe")
        finally:
            self.updater.launch_installer = original
        self.assertEqual(self.scheduled, [])
        self.assertEqual(self.box.calls[-1][0], "showerror")

    def test_a_source_copy_never_checks_and_explains_when_asked(self):
        original = self.updater.find_update
        self.updater.find_update = lambda *a, **k: self.fail("a development copy must not look for updates")
        try:
            self.app._start_update_check()
            self.app.check_for_updates()
        finally:
            self.updater.find_update = original
        self.assertEqual(self.tasks, [])
        self.assertIn("source files", self.box.calls[-1][1][1])

    def test_the_setting_can_switch_the_check_off(self):
        settings = self.gui.settings
        self.assertTrue(settings.update_check_enabled({}))
        self.assertTrue(settings.update_check_enabled({"update_check": True}))
        for off in (False, "false", "No", "off"):
            self.assertFalse(settings.update_check_enabled({"update_check": off}), off)


class OpenWiring(unittest.TestCase):
    """The Open and Open Drawing buttons: which file opens, and when the user is asked which revision."""
    A = ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"]
    B = ["cad/HCR-00007-001_B.SLDPRT", "cad/HCR-00007-001_B.SLDDRW"]

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        from litterbox.parts.engine import PartStatus
        from litterbox.core.pn import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=list(self.B), revision="B",
                              released_revision="A", revisions={"A": self.A, "B": self.B})
        app = self.gui.App.__new__(self.gui.App)
        app.rows_by_pn = {self.pn: self.row}
        app._selected_pns = lambda action=None: [self.pn]
        app.repo = lambda: "C:/vault"
        app.settings = {"open_with": {".pdf": "x"}}
        self.said = []
        app._say = lambda text, tone="normal": self.said.append(text)
        self.app = app
        self.opened, self.asked = [], []
        original_open = self.gui.opener.open_path
        self.addCleanup(setattr, self.gui.opener, "open_path", original_open)     # don't leak into other tests
        self.gui.opener.open_path = lambda path, settings=None: self.opened.append((Path(path).name, settings))

        outer = self

        class FakePicker:
            answer = "A"

            def __init__(self, parent, pn, choices, title="Open"):
                outer.asked.append(([label for label, _rev in choices], title))

            def show(self):
                return FakePicker.answer
        self.picker = FakePicker
        self.gui.RevisionPickerDialog = FakePicker

    def test_a_released_and_a_working_revision_ask_which_to_open(self):
        self.app.open_part()
        self.assertEqual(self.asked, [(["Rev B (working)", "Rev A (released)"], "Open")])
        self.assertEqual(self.opened, [("HCR-00007-001_A.SLDPRT", {".pdf": "x"})])      # answered A

    def test_cancelling_the_question_opens_nothing(self):
        self.picker.answer = None
        self.app.open_part()
        self.assertEqual(self.opened, [])

    def test_open_drawing_asks_too_when_both_revisions_have_a_drawing(self):
        self.picker.answer = "B"
        self.app.open_part(drawing=True)
        self.assertEqual(self.asked[0][1], "Open drawing of")
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDDRW")

    def test_no_question_when_there_is_only_one_revision_to_open(self):
        self.row.released_revision = ""
        self.row.revisions = {"B": self.B}
        self.app.open_part()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")

    def test_open_drawing_with_a_drawing_in_one_revision_does_not_ask(self):
        self.row.revisions = {"A": self.A, "B": ["cad/HCR-00007-001_B.SLDPRT"]}
        self.app.open_part(drawing=True)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.opened[0][0], "HCR-00007-001_A.SLDDRW")

    # -- out-of-date parts offered when an assembly in work is opened -------------------------
    def _stale(self, replaceable=True):
        from types import SimpleNamespace as S
        from litterbox.core.pn import PN
        return S(child=PN("HCR", 3, 1), child_revision="A", latest_released="B", replaceable=replaceable)

    def test_opening_an_assembly_with_out_of_date_parts_offers_a_review(self):
        replace(self, self.gui.references, "uses", lambda repo, pn, rev: [self._stale()])
        asked, loaded = [], []
        self.box.askyesno = lambda title, text: asked.append((title, text)) or True
        self.gui.messagebox.askyesno = self.box.askyesno
        self.app._load_references = lambda pn: loaded.append(pn)
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(loaded, [self.pn])
        self.assertEqual(self.opened, [])
        self.assertIn("newer released revision", asked[0][1])

    def test_declining_the_review_opens_the_file_anyway(self):
        replace(self, self.gui.references, "uses", lambda repo, pn, rev: [self._stale()])
        self.gui.messagebox.askyesno = lambda title, text: False
        self.app._load_references = lambda pn: self.fail("should not review")
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(self.opened[0][0], "HCR-00007-001_B.SLDPRT")

    def test_no_offer_for_the_released_revision_or_when_nothing_can_change(self):
        replace(self, self.gui.references, "uses", lambda repo, pn, rev: [self._stale()])
        self.gui.messagebox.askyesno = lambda *a: self.fail("should not ask")
        self.picker.answer = "A"                        # the released revision: frozen, nothing to replace
        self.app.open_part()
        self.assertEqual(len(self.opened), 1)
        replace(self, self.gui.references, "uses", lambda repo, pn, rev: [self._stale(False)])
        self.picker.answer = "B"
        self.app.open_part()
        self.assertEqual(len(self.opened), 2)

    def test_history_window_can_open_a_chosen_revision(self):
        self.app._open_revision(self.pn, "A", False)
        self.app._open_revision(self.pn, "B", True)
        self.assertEqual([name for name, _s in self.opened], ["HCR-00007-001_A.SLDPRT", "HCR-00007-001_B.SLDDRW"])
        self.app._open_revision(self.pn, "C", False)
        self.assertIn("no file", self.said[-1])


class ListAndFilenameWiring(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.parts.engine import PartStatus
        from litterbox.core.pn import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Bracket", "in_work", "Available (Rev A released)", "ok",
                              files=["cad/HCR-00007-001_B.SLDPRT"], revision="B", released_revision="A",
                              revisions={"B": ["cad/HCR-00007-001_B.SLDPRT"]})

    def test_the_list_shows_the_short_part_number_and_the_revision(self):
        app = self.gui.App.__new__(self.gui.App)
        app.jobs = fake_jobs()
        app.rows = [self.row]
        app.search = types.SimpleNamespace(get=lambda: "")
        app.view = types.SimpleNamespace(get=lambda: "All")
        app.void_box = types.SimpleNamespace(get=lambda: 0)
        app.ticked = set()
        app.tree = SortableFakeTree(["tick", "pn", "name", "description", "cots", "rev", "state", "files"])
        app.sorter = self.gui.TableSorter(app.tree, [])
        self.assertEqual(app._render(), 1)
        self.assertEqual(app.tree.rows["HCR-00007-001"]["values"],
                         ["\u2610", "00007-001", "Bracket", "", "", "B", "Available (Rev A released)", "PRT"])

    def test_a_voided_part_that_is_hidden_loses_its_tick(self):
        from litterbox.parts.engine import PartStatus
        voided = PartStatus(self.pn, "Bracket", "void", "Void", "void")
        for shown, expected in ((0, set()), (1, {"HCR-00007-001"})):
            app = self.gui.App.__new__(self.gui.App)
            app.jobs = fake_jobs()
            app.rows = [voided]
            app.search = types.SimpleNamespace(get=lambda: "")
            app.view = types.SimpleNamespace(get=lambda: "All")
            app.void_box = types.SimpleNamespace(get=lambda shown=shown: shown)
            app.ticked = {"HCR-00007-001"}
            app.tree = SortableFakeTree(["tick", "pn", "name", "description", "cots", "rev", "state", "files"])
            app.sorter = self.gui.TableSorter(app.tree, [])
            app._render()
            self.assertEqual(app.ticked, expected)

    def test_search_finds_a_part_by_the_short_or_the_full_number(self):
        for text in ("00007-001", "HCR-00007-001"):
            self.assertEqual(len(self.gui.logic.filter_rows([self.row], text)), 1)

    def test_new_part_shows_the_filename_to_save_as_and_copies_it(self):
        dialog = self.gui.FilenameDialog(FakeParent(), self.pn)
        self.assertEqual(dialog.stem, "HCR-00007-001_A")
        copied = []
        dialog.clipboard_clear = lambda: copied.append("cleared")
        dialog.clipboard_append = copied.append
        dialog._copy()
        self.assertEqual(copied, ["cleared", "HCR-00007-001_A"])


class SortableFakeTree(FakeTree):
    def __init__(self, columns):
        super().__init__(None, columns)
        self.titles, self.commands = {}, {}

    def heading(self, column, text=None, command=None, **kwargs):
        if text is not None:
            self.titles[column] = text
        if command is not None:
            self.commands[column] = command

    def move(self, iid, parent, position):
        order = [i for i in self.rows if i != iid]
        order.insert(position, iid)
        self.rows = {i: self.rows[i] for i in order}


class TableSorting(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        self.tree = SortableFakeTree(["pn", "files"])
        for iid, files in (("A", "PRT"), ("B", "ASM, DRW"), ("C", ""), ("D", "ASM")):
            self.tree.insert("", "end", iid=iid, values=[iid, files])
        self.sorter = self.gui.TableSorter(self.tree, [("pn", "Part number"), ("files", "Files")])

    def test_clicking_a_heading_sorts_then_reverses_with_an_arrow(self):
        self.tree.commands["files"]()
        self.assertEqual(list(self.tree.rows), ["D", "B", "A", "C"])        # ASM, ASM+DRW, PRT, blank last
        self.assertEqual(self.tree.titles["files"], "Files ▲")
        self.assertEqual(self.tree.titles["pn"], "Part number")
        self.tree.commands["files"]()
        self.assertEqual(list(self.tree.rows), ["A", "B", "D", "C"])
        self.assertEqual(self.tree.titles["files"], "Files ▼")
        self.tree.commands["pn"]()                                          # a new column starts ascending
        self.assertEqual(list(self.tree.rows), ["A", "B", "C", "D"])
        self.assertEqual((self.tree.titles["pn"], self.tree.titles["files"]), ("Part number ▲", "Files"))

    def test_the_sort_is_kept_when_the_table_is_redrawn(self):
        self.tree.commands["files"]()
        self.tree.delete(*self.tree.get_children())
        for iid, files in (("A", "PRT"), ("B", "ASM, DRW"), ("E", "ASM")):
            self.tree.insert("", "end", iid=iid, values=[iid, files])
        self.sorter.apply()
        self.assertEqual(list(self.tree.rows), ["E", "B", "A"])


class WindowEffects(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())

    def test_a_window_starts_invisible_fades_in_and_fades_out_before_closing(self):
        window = FakeWindow()
        self.gui.set_window_icon(window)
        self.assertEqual(window.alpha, 0.0)                    # hidden while the icon is applied
        window.run_timers()                                    # the 0.4 s safety net reveals it
        rising = window.alphas[1:]
        self.assertEqual(rising[-1], 1.0)
        self.assertEqual(rising, sorted(rising))
        self.assertGreater(len(set(rising)), 3)                # a real fade, not a jump
        window.alphas.clear()
        window.destroy()                                       # the overridden destroy
        self.assertFalse(window.destroyed)                     # still on screen, fading
        window.destroy()                                       # a second close request is ignored
        window.run_timers()
        self.assertTrue(window.destroyed)
        self.assertEqual(window.alphas, sorted(window.alphas, reverse=True))
        self.assertEqual(window.alphas[-1], 0.0)

    def test_the_icon_is_put_back_after_customtkinter_resets_it(self):
        replace(self, self.gui.logic, "find_icon", lambda *a, **k: Path("litterbox.ico"))
        window = FakeWindow()
        self.gui.set_window_icon(window)
        window.run_timers()
        # once at creation, once when revealed, and again at 250, 500 and 900 ms
        self.assertGreaterEqual(window.icon_calls, 5)

    def test_the_main_windows_close_button_goes_through_the_fade(self):
        main, other = FakeWindow(), FakeWindow()
        self.gui.set_window_icon(main, main_window=True)
        self.gui.set_window_icon(other)
        self.assertIs(main.protocols["WM_DELETE_WINDOW"], main.destroy)
        self.assertFalse(hasattr(other, "protocols"))

    def test_closing_before_it_was_ever_shown_just_closes(self):
        window = FakeWindow()
        self.gui.set_window_icon(window)
        window.destroy()
        self.assertTrue(window.destroyed)


@SKIP_ON_WINDOWS
class ImportWindowWiring(ImportFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        patcher = mock.patch.object(settings, "ROOT", self.tmp / "litterbox-settings")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.imported = []
        self.window = self.open_window()

    def open_window(self, cots=False):
        with mock.patch.object(import_session, "ImportSession", lambda *a, **k: self.make_session(*a, **k)):
            return self.gui.ImportWindow(FakeParent(), str(self.a), "HCR", self.imported.append, cots=cots)

    def make_session(self, repo, post, log=None, org=None):
        self.session = REAL_SESSION(repo, post, backend_factory=lambda: self.fake, log=log or (lambda t: None),
                                                    org=org, gap=0, jitter=0)
        self.addCleanup(lambda: (self.session.close(), self.session._thread.join(5)))
        return self.session

    def pump_until_idle(self):
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                work = self.window.inbox.get(timeout=0.2)
            except queue.Empty:
                if not self.window.running:
                    return
                continue
            work()
            if not self.window.running:
                return
        self.fail("the background job never finished")

    def scan(self):
        self.window.folders.append(str(self.src))
        with self.user("Alex"):
            self.window._scan()
            self.assertTrue(self.window.running)
            self.pump_until_idle()

    def rows(self):
        return list(self.window.tree.rows.values())

    # -- tests -------------------------------------------------------------------
    def test_scanning_fills_the_table(self):
        self.scan()
        self.assertEqual(self.window.mode, "table")
        self.assertEqual(len(self.rows()), 4)
        first = self.rows()[0]["values"]
        self.assertEqual(first[0], "☑")
        self.assertTrue(first[1].startswith("HCR-"))
        self.assertEqual(self.window.primary.options["text"], "Finish & Import")
        self.assertIn("4 of 4", self.window.summary.options["text"])

    def test_scanning_with_no_folder_says_so(self):
        self.window._scan()
        self.assertIn("Add at least one folder", self.window.status.options["text"])
        self.assertEqual(self.window.mode, "pick")

    def test_a_bad_scan_goes_back_to_the_first_page_with_a_message(self):
        self.window.folders.append(str(self.tmp / "does-not-exist"))
        self.window._scan()
        self.pump_until_idle()
        self.assertEqual(self.window.mode, "pick")
        self.assertTrue(any(c[0] == "showerror" for c in self.box.calls))

    def test_unticking_a_row_updates_the_table(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        event = types.SimpleNamespace(x=5, y=5)
        self.window.tree.identify_region = lambda x, y: "cell"
        self.window.tree.identify_column = lambda x: "#1"
        self.window.tree.identify_row = lambda y: iid
        with self.user("Alex"):
            self.window._on_click(event)
            self.pump_until_idle()
        self.assertEqual(self.window.tree.rows[iid]["values"][0], "☐")
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("off",))
        self.assertIn("3 of 4", self.window.summary.options["text"])

    def click(self, iid, shift=False):
        tree = self.window.tree
        tree.identify_region = lambda x, y: "cell"
        tree.identify_column = lambda x: "#1"
        tree.identify_row = lambda y: iid
        with self.user("Alex"):
            self.window._on_click(types.SimpleNamespace(x=5, y=5, state=1 if shift else 0))
            self.pump_until_idle()

    def marks(self):
        return [r["values"][0] for r in self.rows()]

    def test_shift_click_selects_or_deselects_everything_between(self):
        self.scan()
        ids = list(self.window.tree.rows)
        self.click(ids[0])                                    # deselect the first
        self.click(ids[2], shift=True)                        # and everything down to the third
        self.assertEqual(self.marks(), ["☐", "☐", "☐", "☑"])
        self.click(ids[3])                                    # deselect the last
        self.click(ids[0])                                    # select the first again
        self.click(ids[2], shift=True)                        # and everything down to the third
        self.assertEqual(self.marks(), ["☑", "☑", "☑", "☐"])

    def test_select_all_and_deselect_all_buttons(self):
        self.scan()
        with self.user("Alex"):
            self.window._tick_all(False)
            self.pump_until_idle()
            self.assertEqual(self.marks(), ["☐"] * 4)
            self.window._tick_all(True)
            self.pump_until_idle()
        self.assertEqual(self.marks(), ["☑"] * 4)

    def use_family(self, text):
        self.window.family_entry = types.SimpleNamespace(get=lambda: text, configure=lambda **k: None)
        self.window.family_var.set(True)
        with self.user("Alex"):
            self.window._family_toggled()
            self.pump_until_idle()

    def test_same_base_number_box_gives_every_row_a_variant_of_it(self):
        self.scan()
        self.use_family("500")
        self.assertEqual([r["values"][1] for r in self.rows()],
                         [f"HCR-00500-00{n}" for n in (1, 2, 3, 4)])
        self.assertEqual(self.window.family_applied, "500")

    def test_leaving_the_box_empty_uses_the_suggested_number(self):
        self.scan()
        self.window.family_placeholder = "00777"
        self.use_family("")
        self.assertTrue(self.rows()[0]["values"][1].startswith("HCR-00777-"))

    def test_a_base_with_too_few_variants_is_refused_with_a_warning(self):
        self.scan()
        before = [r["values"][1] for r in self.rows()]
        with mock.patch.object(importer.pn_module, "MAX_VARIANT", 3), \
                mock.patch.object(importer.create, "sync_latest", lambda repo: None):      # a sync resets the digit limits
            self.use_family("500")
        self.assertEqual([r["values"][1] for r in self.rows()], before)
        self.assertFalse(self.window.family_var.get())
        self.assertTrue(any(c[0] == "showwarning" and "unused variant" in c[1][1] for c in self.box.calls))

    def test_unticking_the_box_goes_back_to_separate_numbers(self):
        self.scan()
        self.use_family("500")
        self.window.family_var.set(False)
        with self.user("Alex"):
            self.window._family_toggled()
            self.pump_until_idle()
        bases = {r["values"][1].split("-")[1] for r in self.rows()}
        self.assertEqual(len(bases), 4)
        self.assertIsNone(self.window.family_applied)

    def test_editing_a_cell(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        editor = mock.MagicMock()
        editor.get.return_value = "Edited name"
        self.window.editor = (editor, iid, "name")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["values"][2], "Edited name")
        editor.get.return_value = ("banana", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertIn("exactly 5 digits", self.window.status.options["text"])
        self.assertEqual(self.window.status.options["text_color"], self.gui.WARN)

    def test_finish_imports_closes_and_tells_the_main_window(self):
        self.scan()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.assertEqual(len(self.imported[0].pns), 4)
        self.assertTrue(self.window.closed)
        self.assertTrue(any(c[0] == "showinfo" and "Imported 4 parts" in c[1][1] for c in self.box.calls))

    def test_a_taken_typed_number_keeps_the_window_open_with_red_rows(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        editor = mock.MagicMock()
        editor.get.return_value = ("00001", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(self.window.closed)
        self.assertEqual(self.window.mode, "table")
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("conflict",))
        self.assertTrue(any(c[0] == "showwarning" and "Front upright" in c[1][1] for c in self.box.calls))
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()
        # fix the red row and finish again
        editor.get.return_value = ("00900", "001")
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("typed",))
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.assertIn(importer.PN("HCR", 900, 1), self.imported[0].pns)

    def test_cancel_button_during_the_import_returns_to_the_table_with_nothing_added(self):
        self.scan()
        real_copy = self.fake.copy
        calls = {"n": 0}

        def copy(src, dst):
            real_copy(src, dst)
            calls["n"] += 1
            if calls["n"] == 2:
                self.window._cancel_job()          # the user presses Cancel import
        self.fake.copy = copy
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(self.window.closed)
        self.assertEqual(self.window.mode, "table")
        self.assertIn("cancelled", self.window.status.options["text"].lower())
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()

    def test_closing_the_window_during_an_import_cancels_it_and_cleans_up(self):
        self.scan()
        real_copy = self.fake.copy
        calls = {"n": 0}

        def copy(src, dst):
            real_copy(src, dst)
            calls["n"] += 1
            if calls["n"] == 2:
                self.window._close()               # the user closes the window and confirms
        self.fake.copy = copy
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
            while not self.window.closed:
                self.window.inbox.get(timeout=5)()
        self.assertTrue(self.window.closed)
        self.assertEqual(self.imported, [])
        self.assert_nothing_left()

    def test_leaving_the_number_boxes_unchanged_keeps_the_row_automatic(self):
        self.scan()
        iid = next(iter(self.window.tree.rows))
        base, variant = self.window._pn_parts(iid)
        self.assertEqual((len(base), len(variant)), (5, 3))
        editor = mock.MagicMock()
        editor.get.return_value = (base, variant)
        self.window.editor = (editor, iid, "pn")
        self.window._commit_edit()
        self.assertEqual(self.window.tree.rows[iid]["tags"], ("ok",))

    def test_outside_references_ask_the_user_instead_of_failing(self):
        self.scan()
        iid = next(i for i, r in self.window.tree.rows.items() if r["values"][2] == "p1")
        with self.user("Alex"):
            self.window._details[iid].ticked and self.window._run_quick(
                lambda done: self.session.include(int(iid), False, done))
            self.pump_until_idle()
            self.box.calls.clear()
            self.window._finish()
            self.pump_until_idle()                       # asks (the fake answers Yes), then imports
        asked = [c for c in self.box.calls if c[0] == "askyesno"]
        self.assertEqual(len(asked), 1)
        self.assertIn("not being imported", asked[0][1][1])
        self.assertEqual(len(self.imported), 1)
        self.assertEqual(len(self.imported[0].pns), 3)

    def test_saying_no_to_outside_references_imports_nothing(self):
        self.scan()
        iid = next(i for i, r in self.window.tree.rows.items() if r["values"][2] == "p1")
        self.box.answer = False
        with self.user("Alex"):
            self.window._run_quick(lambda done: self.session.include(int(iid), False, done))
            self.pump_until_idle()
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(self.imported, [])
        self.assertFalse(self.window.closed)
        self.assertIn("Nothing was imported", self.window.status.options["text"])
        self.assert_nothing_left()

    # -- Import COTS ----------------------------------------------------------------
    def make_bought_folder(self):
        """A second folder: a copy of p1 (already in the vault after the first import), a part with the
        same name as p3 but different contents, and two identical new parts."""
        bought = self.tmp / "bought"
        bought.mkdir()
        (bought / "bracket_copy.SLDPRT").write_bytes((self.src / "parts" / "p1.SLDPRT").read_bytes())
        (bought / "p3.SLDPRT").write_text("a different p3\n")
        (bought / "91251A540_bolt.SLDPRT").write_text("bolt\n")
        (bought / "bolt_again.SLDPRT").write_text("bolt\n")
        return bought

    def import_everything_first(self):
        with self.user("Alex"):
            self.scan()
            self.window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        self.imported.clear()

    def test_import_cots_needs_the_confirmation_box_before_it_scans(self):
        window = self.open_window(cots=True)
        self.window = window
        self.assertEqual(window.heading, "Import COTS")
        window.folders.append(str(self.src))
        window._scan()
        self.assertEqual(window.mode, "pick")
        self.assertIn("Tick the box", window.status.options["text"])
        window.cots_var.set(True)
        with self.user("Alex"):
            window._scan()
            self.pump_until_idle()
            self.pump_until_idle()
        self.assertEqual(window.mode, "table")

    def test_import_cots_warns_about_duplicates_and_asks_before_importing(self):
        self.import_everything_first()
        bought = self.make_bought_folder()
        window = self.window = self.open_window(cots=True)
        window.cots_var.set(True)
        window.folders.append(str(bought))
        with self.user("Alex"):
            window._scan()
            self.pump_until_idle()               # the scan
            self.pump_until_idle()               # the duplicate check that follows it
            by_name = {r["values"][2]: r for r in window.tree.rows.values()}
            self.assertEqual(by_name["bracket copy"]["tags"], ("warn",))      # same contents as a part in the vault
            self.assertEqual(by_name["p3"]["tags"], ("warn",))                # same name as a part in the vault
            self.assertEqual(by_name["91251A540 bolt"]["tags"], ("warn",))    # identical to another row of this import
            self.box.calls.clear()
            self.box.answer = False                                           # the user says No
            window._finish()
            self.pump_until_idle()
        question = next(c for c in self.box.calls if c[0] == "askyesno")
        self.assertIn("record every one as COTS", question[1][1])
        self.assertIn("identical to the one in the vault", question[1][1])
        self.assertIn("exactly this name", question[1][1])
        self.assertEqual(self.imported, [])
        self.assertIn("Nothing was imported", window.status.options["text"])
        self.assertEqual(len(list((self.a / "PN-logs").iterdir())), 5)         # only the first import's records
        self.box.answer = True                                                 # the user says Yes
        with self.user("Alex"):
            window._finish()
            self.pump_until_idle()
        self.assertEqual(len(self.imported), 1)
        records = [registry.load(self.a, pn) for pn in self.imported[0].pns]
        self.assertEqual(len(records), 4)
        self.assertTrue(all(r.cots and r.imported for r in records))

    def test_a_normal_import_never_asks_the_cots_question_or_marks_cots(self):
        self.scan()
        self.box.calls.clear()
        with self.user("Alex"):
            self.window._finish()
            self.pump_until_idle()
        self.assertFalse(any(c[0] == "askyesno" for c in self.box.calls))
        self.assertTrue(all(not registry.load(self.a, pn).cots for pn in self.imported[0].pns))

    def test_refresh_numbers_reports_the_result(self):
        self.scan()
        with self.user("Alex"):
            self.window._refresh_numbers()
            self.pump_until_idle()
        self.assertIn("available", self.window.status.options["text"])

    def test_the_main_window_has_an_import_button(self):
        source = (Path(__file__).resolve().parents[2] / "litterbox" / "gui" / "litterbox_gui.py").read_text(encoding="utf-8")
        self.assertIn('("Import...", self.import_cad', source)


if __name__ == "__main__":
    unittest.main()
