"""Tests for Home in the main window (home_view.py, home_actions.py): its rows, ticks shared with the parts list, the
highlight the details pane and the actions follow, and changing folders (Personal ones at once, Team ones in the
background). The window itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not
the look. Please also try the real window."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.folders import folder_access
from litterbox.folders import folder_model
from litterbox.folders import personal_folders
from litterbox.folders.folder_actions import Place
from litterbox.folders.folder_store import Trees
from litterbox.parts.part_status import PartStatus
from litterbox.team import team_identity
from tests.support.gui_fakes import FakeBox, FakeTree, SortableFakeTree, fake_jobs, load_gui_with_fakes, replace

PART, OTHER = PN("HCR", 1, 1), PN("HCR", 2, 1)


class HomeWiring(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        App = self.gui.app.App
        app = App.__new__(App)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "HCR.yaml"
        app.personal_path = lambda: self.path
        app.ticked, app.tree, app.home = set(), SortableFakeTree(["pn"]), FakeTree()
        app.home_shown, app.home_rows, app.doc_rows = True, {}, []
        app.rows_by_pn = {PART: PartStatus(PART, "Bracket", "in_work", "s", "ok"),
                          OTHER: PartStatus(OTHER, "Nut", "in_work", "s", "mine")}
        app.icons = SimpleNamespace(tick=lambda size, on: f"tick-{on}", icon=lambda name, size, color: name)
        app._px = lambda size: size
        app.search = SimpleNamespace(get=lambda: "")
        app.identity = team_identity.Identity(team_identity.LEGACY)
        app.home_projects = []
        shared = folder_model.build([{"op": "add", "folder": "t1", "parent": "", "name": "Shared"},
                                     {"op": "put", "folder": "t1", "items": [str(PART), "ECO-0001"]}])
        app.home_trees = Trees(team=shared)
        app.jobs = fake_jobs()
        self.said, self.tasks = [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app._update_buttons = lambda: None
        app.run_task = lambda work, done, **kwargs: self.tasks.append((work, kwargs))
        app.repo = lambda: "C:/vault"
        self.app = app
        app._load_personal()
        app._render_home()

    def test_rows_ticks_and_the_highlight(self):
        item = "i|team|t1|HCR-00001-001"
        self.assertEqual(self.app.home.rows[item]["text"], "  HCR-00001-001   Bracket")
        self.assertEqual(self.app.home.rows[item]["image"], "tick-False")
        self.app._set_home_ticks([str(PART)], True)
        self.assertEqual(self.app.ticked, {str(PART)})
        self.assertEqual(self.app.home.rows[item]["image"], "tick-True")
        self.assertEqual(self.app._ticked_pns(), [PART])                     # Home's ticks drive the actions
        self.app.home.selection_set(item)
        self.assertEqual(self.app._highlighted_pns(), [PART])
        self.app.home.selection_set("f|team|t1")
        self.assertEqual(self.app._highlighted_pns(), [])
        self.app.home.selection_set("i|team|t1|ECO-0001")
        self.assertEqual(self.app._highlighted_pns(), [])                     # an ECO isn't a part

    def test_a_personal_folder_is_made_at_once(self):
        top = self.app.home_rows["top:personal"]
        replace(self, self.app, "_ask", lambda text, title: "To review")
        self.app.new_folder(top)
        tree = personal_folders.load(self.path)
        self.assertEqual([f.name for f in tree.values()], ["To review"])
        self.assertIn("f|personal|" + next(iter(tree)), self.app.home.rows)
        self.assertEqual(self.tasks, [])

    def test_add_to_folder_puts_the_ticked_parts_in_the_chosen_folder(self):
        folder = folder_model.new_id()
        new = {"op": "add", "folder": folder, "parent": "", "name": "Picked"}
        picked = []

        class Picker:
            def __init__(self, parent, places, count):
                picked.append(([title for _p, title, _t in places], count))

            def show(self):
                return Place(folder_access.PERSONAL), folder, [new]

        replace(self, self.gui.folder_picker_dialog, "FolderPickerDialog", Picker)
        self.app.add_to_folder([str(PART), str(OTHER)])
        self.assertEqual(picked, [(["Personal", "Team"], 2)])
        self.assertEqual(personal_folders.load(self.path)[folder].items, [str(PART), str(OTHER)])

    def test_add_to_folder_can_put_them_in_a_top(self):
        class Picker:
            def __init__(self, parent, places, count):
                pass

            def show(self):
                return Place(folder_access.PERSONAL), "", []

        replace(self, self.gui.folder_picker_dialog, "FolderPickerDialog", Picker)
        self.app.add_to_folder([str(PART)])
        self.assertEqual(personal_folders.load(self.path)[""].items, [str(PART)])
        self.assertIn("i|personal||HCR-00001-001", self.app.home.rows)

    def test_add_parts_offers_what_the_folder_lacks_and_puts_the_chosen(self):
        offered = []

        class Picker:
            def __init__(self, parent, rows, heading="", **kwargs):
                offered.append(([str(r.pn) for r in rows], heading))

            def show(self):
                return [OTHER]

        replace(self, self.gui.part_picker_dialog, "PartPickerDialog", Picker)
        replace(self, self.gui.home_actions.folder_actions, "apply_change", lambda *a, **kw: None)
        self.app.add_parts(self.app.home_rows["f|team|t1"])
        self.assertEqual(offered, [([str(OTHER)], "Add parts to Shared")])     # PART is in it already
        self.assertEqual(self.app.home_trees.team["t1"].items, [str(PART), "ECO-0001", str(OTHER)])

    def test_an_item_dropped_on_a_top_moves_out_of_its_folder(self):
        replace(self, self.gui.home_actions.folder_actions, "apply_change", lambda *a, **kw: None)
        self.app._drop_item(self.app.home_rows["i|team|t1|HCR-00001-001"], self.app.home_rows["top:team"])
        self.assertEqual(self.app.home_trees.team["t1"].items, ["ECO-0001"])
        self.assertIn("i|team||HCR-00001-001", self.app.home.rows)

    def test_a_team_change_shows_now_and_uploads_in_the_background(self):
        made = []
        replace(self, self.gui.home_actions.folder_actions, "apply_change",
                lambda repo, place, ops, message, **kw: made.append((place, ops, message)))
        row = self.app.home_rows["i|team|t1|HCR-00001-001"]
        self.app.remove_item(row)
        self.assertEqual(self.app.home_trees.team["t1"].items, ["ECO-0001"])    # shown at once
        self.assertNotIn("i|team|t1|HCR-00001-001", self.app.home.rows)
        work, kwargs = self.tasks[0]
        self.assertEqual(kwargs["label"], "Saving folders")
        work()
        self.assertEqual(made[0][0], Place(folder_access.TEAM))
        self.assertEqual(made[0][1], [{"op": "take", "folder": "t1", "items": [str(PART)]}])

    def test_a_change_you_may_not_make_is_refused_with_why(self):
        person = SimpleNamespace(id="bea", active=True, access="member", roles=[])
        self.app.identity = team_identity.Identity(team_identity.OK, person=person,
                                                   directory=SimpleNamespace(may_change_team_folders=lambda p: False))
        self.app.remove_item(self.app.home_rows["i|team|t1|HCR-00001-001"])
        self.assertIn("Only Admins, the Owner", self.said[-1])
        self.assertEqual(self.tasks, [])


if __name__ == "__main__":
    unittest.main()
