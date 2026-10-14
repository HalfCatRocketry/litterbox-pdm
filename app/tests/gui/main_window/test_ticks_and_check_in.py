"""Tests for ticking parts, check in and saving in the main window. The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real window."""

import unittest
from litterbox.errors import NothingToSaveError
from tests.support.gui_fakes import FakeBox, fake_jobs, load_gui_with_fakes, SortableFakeTree


class TickAndSaveWiring(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        from litterbox.core.part_number import PN
        self.PN = PN
        app = self.gui.app.App.__new__(self.gui.app.App)
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
        from litterbox.parts.part_status import PartStatus
        app = self.app
        app.jobs = fake_jobs()
        app.rows_by_pn = {self.PN.parse if False else None: None}
        pns = {n: self.PN("HCR", n, 1) for n in (1, 2, 3)}
        kinds = {1: "ok", 2: "mine", 3: "released"}
        app.rows_by_pn = {pns[n]: PartStatus(pns[n], "x", "in_work", "s", kinds[n]) for n in pns}
        app.action_buttons = {text: SimpleNamespace(state=None, configure=lambda state, b=None: None)
                              for text in self.gui.action_rules.BUTTON_ACTIONS}
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
        window = self.gui.references_window.ReferencesWindow.__new__(self.gui.references_window.ReferencesWindow)
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
        app._finish(self.gui.jobs.Outcome(job, error=NothingToSaveError("Nothing was different.")))
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


if __name__ == "__main__":
    unittest.main()
