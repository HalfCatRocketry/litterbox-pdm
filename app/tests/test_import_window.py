"""
Smoke test for the Import window in litterbox_gui.py, with the screen replaced by stand-ins.

No real window is opened (so this runs anywhere, even without tkinter): customtkinter and tkinter
are replaced by simple fakes, a fake table remembers its rows, and the test plays the user by calling
the same functions the buttons call. It checks the wiring - the right things are shown, buttons call the
right session steps, errors reach the user - not how the window looks. Please also try the real window.

Run from the app folder with:  python -m unittest discover -s tests -v
"""

import importlib.util
import queue
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
from test_importer import ImportFixture  # noqa: E402
from vault_fixture import SKIP_ON_WINDOWS  # noqa: E402

import import_session  # noqa: E402
import importer  # noqa: E402
import registry  # noqa: E402
import settings  # noqa: E402


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

    def selection(self):
        return self.chosen

    def selection_set(self, *ids):
        self.chosen = ids

    def set(self, iid, column):
        return self.rows[iid]["values"][self.columns.index(column)]


class FakeBox:
    def __init__(self):
        self.calls = []
        self.answer = True              # what Yes/No questions are answered with

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            return self.answer if name == "askyesno" else None
        return call


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
    for name in ("showinfo", "showwarning", "showerror", "askyesno"):
        setattr(mbox, name, getattr(box, name))
    tk.filedialog, tk.messagebox, tk.ttk = dialogs, mbox, ttk
    fakes = {"customtkinter": ctk, "tkinter": tk, "tkinter.ttk": ttk, "tkinter.filedialog": dialogs,
             "tkinter.messagebox": mbox}
    app = Path(__file__).resolve().parent.parent / "litterbox_gui.py"
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
        import people
        from litterbox_engine import PartStatus
        from pn import PN
        self.people = people
        self.pn = PN("HCR", 7, 1)
        row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=["cad/HCR-00007-001_A.SLDPRT"],
                         revisions={"A": ["cad/HCR-00007-001_A.SLDPRT"]})
        app = self.gui.App.__new__(self.gui.App)
        app.rows_by_pn = {self.pn: row}
        app._selected_pns = lambda: [self.pn]
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
        self.app.busy = False
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
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False: self.tasks.append(
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
        app.run_task = lambda work, done, on_success=None, refresh=True, is_refresh=False: self.tasks.append(
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
        from litterbox_engine import LitterboxError
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
        from litterbox_engine import PartStatus
        from pn import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Part", "in_work", "Available", "ok", files=list(self.B), revision="B",
                              released_revision="A", revisions={"A": self.A, "B": self.B})
        app = self.gui.App.__new__(self.gui.App)
        app.rows_by_pn = {self.pn: self.row}
        app._selected_pns = lambda: [self.pn]
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
        from pn import PN
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
        from litterbox_engine import PartStatus
        from pn import PN
        self.pn = PN("HCR", 7, 1)
        self.row = PartStatus(self.pn, "Bracket", "in_work", "Available (Rev A released)", "ok",
                              files=["cad/HCR-00007-001_B.SLDPRT"], revision="B", released_revision="A",
                              revisions={"B": ["cad/HCR-00007-001_B.SLDPRT"]})

    def test_the_list_shows_the_short_part_number_and_the_revision(self):
        app = self.gui.App.__new__(self.gui.App)
        app.rows = [self.row]
        app.search = types.SimpleNamespace(get=lambda: "")
        app.view = types.SimpleNamespace(get=lambda: "All")
        app.void_box = types.SimpleNamespace(get=lambda: 0)
        app.tree = SortableFakeTree(["pn", "name", "description", "cots", "rev", "state", "files"])
        app.sorter = self.gui.TableSorter(app.tree, [])
        self.assertEqual(app._render(), 1)
        self.assertEqual(app.tree.rows["HCR-00007-001"]["values"],
                         ["00007-001", "Bracket", "", "", "B", "Available (Rev A released)", "PRT"])

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
        source = (Path(__file__).resolve().parent.parent / "litterbox_gui.py").read_text(encoding="utf-8")
        self.assertIn('("Import...", self.import_cad', source)


if __name__ == "__main__":
    unittest.main()