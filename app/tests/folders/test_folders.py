"""Tests for folders without git: the changes and the trees they build (folders/folder_model.py), the checked
changes the window asks for (folder_actions.py), Personal folders on this computer (personal_folders.py), the
vault's change files read back (folder_store.py), who sees and changes which (folder_access.py), Home's rows
(gui/logic/folder_text.py), and the team's Team folders roles and a project's "only the Lead" switch."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core import projects as project_rules
from litterbox.core.part_number import PN
from litterbox.folders import folder_access
from litterbox.folders import folder_actions
from litterbox.folders import folder_model
from litterbox.folders import folder_store
from litterbox.folders import personal_folders
from litterbox.folders.folder_actions import Place
from litterbox.folders.folder_model import FolderError
from litterbox.gui.logic import folder_text
from litterbox.team import team_identity
from litterbox.team import team_model

TEAM, PERSONAL = Place(folder_access.TEAM), Place(folder_access.PERSONAL)


def tree_with(*names):
    """A tree with these folders at the top, ids f1, f2, ..."""
    return folder_model.build({"op": "add", "folder": f"f{n}", "parent": "", "name": name}
                              for n, name in enumerate(names, 1))


class Model(unittest.TestCase):
    def test_folders_and_what_they_hold(self):
        tree = tree_with("Brackets")
        folder_model.apply(tree, {"op": "add", "folder": "in", "parent": "f1", "name": "Left"})
        folder_model.apply(tree, {"op": "put", "folder": "f1", "items": ["HCR-00001-001", "PROP-0001"]})
        folder_model.apply(tree, {"op": "put", "folder": "f1", "items": ["HCR-00001-001", "ECO-0002"]})
        self.assertEqual(tree["f1"].items, ["HCR-00001-001", "PROP-0001", "ECO-0002"])        # each once
        folder_model.apply(tree, {"op": "take", "folder": "f1", "items": ["PROP-0001"]})
        self.assertEqual(tree["f1"].items, ["HCR-00001-001", "ECO-0002"])
        self.assertEqual(folder_model.path_of(tree, "in"), ["Brackets", "Left"])
        self.assertEqual([f.name for f in folder_model.children(tree)], ["Brackets"])

    def test_deleting_takes_the_folders_inside_and_late_changes_do_nothing(self):
        tree = tree_with("Brackets")
        folder_model.apply(tree, {"op": "add", "folder": "in", "parent": "f1", "name": "Left"})
        self.assertTrue(folder_model.apply(tree, {"op": "delete", "folder": "f1"}))
        self.assertEqual(tree, {})
        for late in ({"op": "put", "folder": "in", "items": ["x"]}, {"op": "rename", "folder": "f1", "name": "y"},
                     {"op": "add", "folder": "z", "parent": "f1", "name": "z"}, {"op": "spin", "folder": "f1"}):
            self.assertFalse(folder_model.apply(tree, late))

    def test_a_folder_never_moves_inside_itself(self):
        tree = tree_with("Top")
        folder_model.apply(tree, {"op": "add", "folder": "in", "parent": "f1", "name": "Inner"})
        self.assertFalse(folder_model.apply(tree, {"op": "move", "folder": "f1", "parent": "in"}))
        self.assertTrue(folder_model.apply(tree, {"op": "move", "folder": "in", "parent": ""}))
        self.assertEqual(tree["in"].parent, "")

    def test_a_tree_written_as_changes_builds_the_same_tree(self):
        tree = tree_with("B", "A")
        folder_model.apply(tree, {"op": "add", "folder": "in", "parent": "f1", "name": "Inner"})
        folder_model.apply(tree, {"op": "put", "folder": "in", "items": ["HCR-00001-001"]})
        self.assertEqual(folder_model.build(folder_model.to_ops(tree)), tree)
        self.assertEqual([f.name for f in folder_model.children(tree)], ["A", "B"])

    def test_items_at_the_top_of_a_tree(self):
        tree = tree_with("Brackets")
        self.assertFalse(folder_model.apply(tree, {"op": "take", "folder": "", "items": ["x"]}))
        self.assertEqual(list(tree), ["f1"])                                     # nothing made for a take
        self.assertTrue(folder_model.apply(tree, {"op": "put", "folder": "", "items": ["HCR-00001-001"]}))
        self.assertEqual(folder_model.holder(tree, "").items, ["HCR-00001-001"])
        self.assertEqual([f.name for f in folder_model.children(tree)], ["Brackets"])    # the top isn't a folder
        self.assertEqual([f.id for f in folder_model.folders(tree)], ["f1"])
        for refused in ({"op": "delete", "folder": ""}, {"op": "rename", "folder": "", "name": "x"},
                        {"op": "move", "folder": "", "parent": "f1"}, {"op": "add", "folder": "", "parent": "",
                                                                       "name": "x"}):
            self.assertFalse(folder_model.apply(tree, refused))
        self.assertIn("f1", tree)
        self.assertEqual(folder_model.build(folder_model.to_ops(tree)), tree)
        self.assertTrue(folder_model.apply(tree, {"op": "delete", "folder": "f1"}))
        self.assertEqual(folder_model.holder(tree, "").items, ["HCR-00001-001"])     # deleting a folder leaves it
        self.assertEqual(folder_model.path_of(tree, ""), [])

    def test_names(self):
        self.assertEqual(folder_model.check_name("  Brackets   left "), "Brackets left")
        for bad in ("", "   ", "x" * (folder_model.NAME_MAX + 1)):
            with self.assertRaises(FolderError):
                folder_model.check_name(bad)


class Actions(unittest.TestCase):
    def test_the_checked_changes(self):
        tree = tree_with("Brackets")
        add = folder_actions.add_folder(tree, "", "Nuts")
        self.assertEqual((add["op"], add["parent"], add["name"]), ("add", "", "Nuts"))
        with self.assertRaisesRegex(FolderError, "already a folder called brackets"):
            folder_actions.add_folder(tree, "", "brackets")
        with self.assertRaises(FolderError):
            folder_actions.add_folder(tree, "gone", "Nuts")
        folder_model.apply(tree, add)
        with self.assertRaises(FolderError):
            folder_actions.rename_folder(tree, "f1", "NUTS")
        self.assertEqual(folder_actions.rename_folder(tree, "f1", "Brackets, left")["name"], "Brackets, left")
        with self.assertRaisesRegex(FolderError, "inside itself"):
            folder_actions.move_folder(tree, "f1", "f1")
        self.assertEqual(folder_actions.put_items(tree, "f1", ["A", "A", "B"])["items"], ["A", "B"])
        folder_model.apply(tree, {"op": "put", "folder": "f1", "items": ["A"]})
        self.assertIsNone(folder_actions.put_items(tree, "f1", ["A"]))
        self.assertEqual(folder_actions.take_items(tree, "f1", ["A", "Z"])["items"], ["A"])
        self.assertIsNone(folder_actions.take_items(tree, "f1", ["Z"]))
        top = folder_actions.put_items(tree, "", ["A"])                       # straight in the top
        self.assertEqual(top, {"op": "put", "folder": "", "items": ["A"]})
        folder_model.apply(tree, top)
        self.assertIsNone(folder_actions.put_items(tree, "", ["A"]))
        self.assertEqual(folder_actions.take_items(tree, "", ["A"])["items"], ["A"])
        with self.assertRaises(FolderError):
            folder_actions.rename_folder(tree, "", "Top")

    def test_personal_changes_go_in_their_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "folders" / "HCR.yaml"
            self.assertEqual(personal_folders.load(path), {})
            add = folder_actions.add_folder({}, "", "Mine")
            folder_actions.apply_change("unused", PERSONAL, [add, None], "Mine: added", personal_path=path)
            folder_actions.apply_change("unused", PERSONAL,
                                        [{"op": "put", "folder": add["folder"], "items": ["HCR-00001-001"]}],
                                        "1 added", personal_path=path)
            tree = personal_folders.load(path)
            self.assertEqual((tree[add["folder"]].name, tree[add["folder"]].items), ("Mine", ["HCR-00001-001"]))
            path.write_text("folders: [not, : valid", encoding="utf-8")
            self.assertEqual(personal_folders.load(path), {})          # a broken file is left alone, not fatal


class Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)

    def test_changes_read_back_in_order_with_a_projects_rename(self):
        write = folder_store.write_change
        write(self.repo, folder_access.TEAM, None, [{"op": "add", "folder": "t", "parent": "", "name": "Shared"}], "Alex")
        write(self.repo, folder_access.PROJECT, "Rover", [{"op": "add", "folder": "r", "parent": "", "name": "Wheels"}],
              "Bea")
        write(self.repo, folder_access.TEAM, None, [{"op": "put", "folder": "t", "items": ["HCR-00001-001"]}], "Bea")
        (self.repo / "folders" / "zz-broken.yaml").write_text(": : :", encoding="utf-8")
        (self.repo / "folders" / "zz-other.yaml").write_text("scope: elsewhere\n", encoding="utf-8")
        trees = folder_store.load(self.repo)
        self.assertEqual(trees.team["t"].items, ["HCR-00001-001"])
        self.assertEqual(trees.projects["Rover"]["r"].name, "Wheels")
        rel = write(self.repo, folder_access.PROJECT, "rover", [{"op": folder_store.RENAMED, "name": "Rover 2"}], "Alex")
        trees = folder_store.load(self.repo)
        self.assertEqual(list(trees.projects), ["Rover 2"])
        self.assertEqual(folder_store.tree_of(trees, folder_access.PROJECT, "rover 2")["r"].name, "Wheels")
        files = [p.name for p in folder_store.change_files(self.repo)]
        self.assertEqual(len(files), 6)
        self.assertEqual(folder_store.unpushed_changes(self.repo, [rel, "cad/x.SLDPRT"] + [f"folders/{files[0]}"]),
                         [(folder_access.TEAM, "")])           # a project's rename alone isn't checked here


def identity(person_id="bea", access=team_model.MEMBER, roles=(), folder_roles=()):
    person = team_model.Person(id=person_id, name=person_id.title(), access=access, roles=list(roles))
    directory = team_model.Directory([person], ["Quality", "Manager"], folder_roles=list(folder_roles))
    return team_identity.Identity(team_identity.OK, person=person, directory=directory)


ROVER = project_rules.with_team(project_rules.new_project("Rover", "12", []), "alex", ["bea"])
MARS = project_rules.with_team(project_rules.new_project("Mars", "13", [ROVER]), "alex", [], hidden=True)


class Access(unittest.TestCase):
    def test_team_folders(self):
        self.assertTrue(folder_access.may_change(identity(access=team_model.ADMIN), folder_access.TEAM)[0])
        self.assertFalse(folder_access.may_change(identity(), folder_access.TEAM)[0])
        self.assertTrue(folder_access.may_change(identity(roles=["manager"], folder_roles=["Manager"]),
                                                 folder_access.TEAM)[0])
        self.assertTrue(folder_access.may_change(identity(), folder_access.PERSONAL)[0])
        legacy = team_identity.Identity(team_identity.LEGACY)
        self.assertTrue(folder_access.may_change(legacy, folder_access.TEAM)[0])
        self.assertFalse(folder_access.may_change(team_identity.Identity(team_identity.NOT_LISTED),
                                                  folder_access.TEAM)[0])

    def test_project_folders(self):
        member, lead = identity(), identity("alex")
        self.assertTrue(folder_access.may_change(member, folder_access.PROJECT, ROVER)[0])
        only_lead = project_rules.with_team(ROVER, "alex", ["bea"], lead_only_folders=True)
        allowed, why = folder_access.may_change(member, folder_access.PROJECT, only_lead)
        self.assertEqual((allowed, why), (False, "Only Rover's Lead changes its folders."))
        self.assertTrue(folder_access.may_change(lead, folder_access.PROJECT, only_lead)[0])
        self.assertFalse(folder_access.may_change(identity("cy"), folder_access.PROJECT, ROVER)[0])
        self.assertFalse(folder_access.may_change(member, folder_access.PROJECT, None)[0])

    def test_which_projects_show(self):
        self.assertEqual(folder_access.shown_projects(identity(), [ROVER, MARS]), [ROVER])
        self.assertEqual(folder_access.shown_projects(identity("alex"), [ROVER, MARS]), [ROVER, MARS])
        self.assertEqual(folder_access.shown_projects(identity("cy"), [ROVER, MARS]), [])
        self.assertEqual(folder_access.shown_projects(identity("cy", team_model.ADMIN), [ROVER, MARS]), [ROVER])
        self.assertEqual(folder_access.check_upload([(folder_access.TEAM, ""), (folder_access.PROJECT, "rover")],
                                                    identity(), [ROVER]),
                         [folder_access.may_change(identity(), folder_access.TEAM)[1]])

    def test_saved_with_the_team_and_the_project(self):
        directory = team_model.Directory([], ["Quality", "Manager"], folder_roles=["manager", "Gone"])
        team_model.validate(directory)
        self.assertEqual(directory.folder_roles, ["Manager"])
        again = team_model.from_dict(directory.to_dict())
        self.assertEqual((again.folder_roles, again.extra), (["Manager"], {}))
        only_lead = project_rules.with_team(ROVER, "alex", ["bea"], lead_only_folders=True)
        data = project_rules.to_data([only_lead])
        self.assertEqual(data[0]["folders"], "lead")
        self.assertTrue(project_rules.from_data(data)[0].lead_only_folders)
        self.assertNotIn("folders", project_rules.to_data([ROVER])[0])


class HomeRows(unittest.TestCase):
    def setUp(self):
        self.personal = tree_with("Mine")
        folder_model.apply(self.personal, {"op": "put", "folder": "f1", "items": ["HCR-00001-001", "ECO-0002"]})
        self.trees = folder_store.Trees(team=tree_with("Shared"), projects={"Rover": tree_with("Wheels")})
        folder_model.apply(self.trees.team, {"op": "add", "folder": "in", "parent": "f1", "name": "Nuts"})
        self.names = {"HCR-00001-001": "Bracket", "ECO-0002": "Lighter frame"}

    def rows(self, search=""):
        return folder_text.home_rows(self.personal, self.trees, [ROVER], lambda item: self.names.get(item, ""), search)

    def test_tops_folders_and_items_on_one_line_each(self):
        rows = self.rows()
        self.assertEqual([(r.kind, r.text) for r in rows], [
            ("top", "Personal"), ("folder", "Mine"), ("item", "HCR-00001-001   Bracket"),
            ("item", "ECO-0002   Lighter frame"), ("top", "Team"), ("folder", "Shared"), ("folder", "Nuts"),
            ("top", "Projects"), ("top", "Rover"), ("folder", "Wheels")])
        item = rows[2]
        self.assertEqual(folder_text.parse_iid(item.iid), ("item", PERSONAL, "f1", "HCR-00001-001"))
        self.assertEqual(folder_text.parse_iid(rows[9].iid)[:3], ("folder", Place(folder_access.PROJECT, "Rover"), "f1"))
        self.assertEqual(rows[6].parent, rows[5].iid)

    def test_search_keeps_what_matches_and_the_folders_it_is_in(self):
        self.assertEqual([r.text for r in self.rows("brack")],
                         ["Personal", "Mine", "HCR-00001-001   Bracket", "Team", "Projects", "Rover"])
        self.assertIn("Nuts", [r.text for r in self.rows("nuts")])

    def test_folders_come_first_then_parts_documents_and_ecos(self):
        folder_model.apply(self.personal, {"op": "put", "folder": "f1", "items": ["PROP-0001", "HCR-00003-001"]})
        folder_model.apply(self.personal, {"op": "add", "folder": "z", "parent": "f1", "name": "Zinc"})
        folder_model.apply(self.personal, {"op": "put", "folder": "", "items": ["ECO-0001", "HCR-00009-001"]})
        rows = self.rows()
        texts = [r.text for r in rows[:rows.index(next(r for r in rows if r.text == "Team"))]]
        self.assertEqual(texts, ["Personal", "Mine", "Zinc", "HCR-00001-001   Bracket", "HCR-00003-001", "PROP-0001",
                                 "ECO-0002   Lighter frame", "HCR-00009-001", "ECO-0001"])
        top_item = next(r for r in rows if r.item == "HCR-00009-001")
        self.assertEqual((top_item.parent, top_item.folder), ("top:personal", ""))
        self.assertEqual(folder_text.parse_iid(top_item.iid), ("item", PERSONAL, "", "HCR-00009-001"))

    def test_what_an_item_points_at(self):
        self.assertEqual(folder_text.parse_item("HCR-00001-001"), ("part", PN("HCR", 1, 1)))
        self.assertEqual(folder_text.parse_item("eco-0002"), ("eco", "ECO-0002"))
        self.assertEqual(folder_text.parse_item("PROP-0001")[0], "document")
        self.assertEqual(folder_text.parse_item("whatever"), ("", "whatever"))
        self.assertEqual(folder_text.item_label("X", ""), "X")


if __name__ == "__main__":
    unittest.main()
