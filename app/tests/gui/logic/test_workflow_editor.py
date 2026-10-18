"""Tests for gui/logic/workflow_editor.py."""

import unittest
from litterbox.gui.logic import workflow_editor


class TestWorkflowEditor(unittest.TestCase):
    ROLES = ["Responsible Engineer", "Quality", "Manager", "Chief"]

    def templates(self):
        from litterbox.workflows import workflow_editing
        t = {}
        workflow_editing.set_template(t, "release", "T1", [["Responsible Engineer"], ["Quality"]])
        workflow_editing.set_template(t, "release", "T2", [["Responsible Engineer"]])
        return t

    def test_nothing_changed_means_no_ops(self):
        editor = workflow_editor.WorkflowEditor(self.templates())
        self.assertFalse(editor.dirty)
        self.assertEqual(editor.ops(), [])
        self.assertEqual(editor.names("release"), ["T1", "T2"])
        self.assertEqual(editor.names("void"), [])

    def test_adding_changing_and_deleting(self):
        editor = workflow_editor.WorkflowEditor(self.templates())
        i = editor.add("void", self.ROLES)
        self.assertEqual((editor.names("void"), editor.items["void"][i]["rows"]), (["T1"], [["Responsible Engineer"]]))
        editor.add_row("release", 0, self.ROLES)
        editor.set_role("release", 0, 2, 0, "Manager")
        self.assertEqual(editor.add_or("release", 0, 2, self.ROLES), "Responsible Engineer")
        editor.delete("release", 1)
        self.assertTrue(editor.dirty)
        ops = editor.ops()
        self.assertEqual([(o["op"], o["action"], o["name"]) for o in ops],
                         [("remove", "release", "T2"), ("set", "release", "T1"), ("set", "void", "T1")])
        self.assertEqual(ops[1]["rows"], [["Responsible Engineer"], ["Quality"], ["Manager", "Responsible Engineer"]])
        self.assertEqual(ops[1]["old"], "T1")
        self.assertIsNone(ops[2]["old"])

    def test_renaming_is_a_set_with_the_old_name(self):
        editor = workflow_editor.WorkflowEditor(self.templates())
        editor.items["release"][0]["name"] = "Flight"
        (op,) = editor.ops()
        self.assertEqual((op["name"], op["old"]), ("Flight", "T1"))

    def test_the_ops_replay_on_newer_files(self):
        from litterbox.workflows import workflow_editing
        editor = workflow_editor.WorkflowEditor(self.templates())
        editor.items["release"][0]["name"] = "Flight"
        editor.delete("release", 1)
        newer = self.templates()
        workflow_editing.set_template(newer, "release", "Other", [["Chief"]])       # someone else's change
        workflow_editing.apply_ops(newer, editor.ops())
        self.assertEqual(list(newer["release"]), ["Flight", "Other"])

    def test_or_rows(self):
        editor = workflow_editor.WorkflowEditor(self.templates())
        editor.add_or("release", 0, 0, self.ROLES)
        editor.remove_or("release", 0, 0, 0)
        self.assertEqual(len(editor.items["release"][0]["rows"][0]), 1)
        editor.remove_or("release", 0, 0, 0)                         # the last role can't be removed
        self.assertEqual(len(editor.items["release"][0]["rows"][0]), 1)

    def test_problems(self):
        editor = workflow_editor.WorkflowEditor(self.templates())
        self.assertEqual(editor.problem(), "")
        editor.items["release"][1]["name"] = "t1"
        self.assertIn("two Release workflows", editor.problem())
        editor.items["release"][1]["name"] = " "
        self.assertIn("needs a name", editor.problem())
        editor.items["release"][1]["name"] = "T2"
        editor.items["release"][1]["rows"] = []
        self.assertIn("at least one sign-off", editor.problem())
        editor.items["release"][1]["rows"] = [["Chief", "chief"]]
        self.assertIn("same role twice", editor.problem())

    def test_standard_workflows_skip_what_lacks_roles(self):
        editor = workflow_editor.WorkflowEditor({})
        added, skipped = editor.add_standard(["Responsible Engineer", "Manager", "Chief"])
        self.assertEqual(added, ["Release T3", "Unrelease T1", "Void T1", "Make COTS T1"])
        self.assertEqual([n for n, _ in skipped], ["Release T1", "Release T2"])
        self.assertEqual(editor.add_standard(["Responsible Engineer", "Manager", "Chief"])[0], [])

    def test_label_for_the_team_window(self):
        self.assertEqual(workflow_editor.ops_label([]), "Workflows")
        ops = [{"action": "release"}, {"action": "void"}, {"action": "release"}]
        self.assertEqual(workflow_editor.ops_label(ops), "Workflows: Release, Void")


if __name__ == "__main__":
    unittest.main()
