"""Tests for Team > Toolbox... (gui/dialogs/toolbox_dialog.py, team_admin.manage_toolbox), the Toolbox rule in Vault
Settings, the warning after a refresh when this computer's SolidWorks uses another Toolbox
(gui/main_window/toolbox_setting.py), and their words (gui/logic/toolbox_text.py). The windows are built on
stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look. Please also try the real windows."""

import unittest
from types import SimpleNamespace

from tests.support.gui_fakes import FakeBox, FakeParent, load_gui_with_fakes, replace

from litterbox.core import toolbox_rules
from litterbox.gui.logic import toolbox_text
from litterbox.vault.toolbox_admin import Status

STATUS = Status(rule=toolbox_rules.TEAM, folder="C:\\Litterbox\\hcr\\toolbox", files=1844, not_downloaded=12,
                changes={"added": ["toolbox/browser/bolt.sldprt"], "changed": [], "removed": []},
                solidworks_folder="C:\\SOLIDWORKS Data (2)\\")


class Words(unittest.TestCase):
    def test_what_an_admin_and_a_member_are_told(self):
        admin = "\n".join(toolbox_text.status_lines(STATUS, admin=True))
        member = "\n".join(toolbox_text.status_lines(STATUS, admin=False))
        self.assertIn("1,844 files in C:\\Litterbox\\hcr\\toolbox (12 not downloaded yet)", admin)
        self.assertIn("uses another Toolbox: C:\\SOLIDWORKS Data (2)\\", admin)
        self.assertIn("Upload them with Upload changes", admin)
        self.assertIn("Only an Admin or the Owner can upload", member)
        self.assertNotIn("Let me change it", member)
        empty = toolbox_text.status_lines(Status(rule=toolbox_rules.NO_TOOLBOX, solidworks_uses_it=True), admin=False)
        self.assertIn("The vault has no Toolbox yet. An Admin or the Owner copies one in.", empty)
        self.assertIn("This computer's SolidWorks uses it.", empty)

    def test_done_text(self):
        self.assertEqual(toolbox_text.done_text("upload", {"added": 2, "changed": 1, "removed": 0}),
                         "Team's Toolbox uploaded: 2 files added, 1 changed")
        self.assertEqual(toolbox_text.done_text("upload", {"added": 0, "changed": 0, "removed": 0}),
                         "The team's Toolbox has no changes to upload")
        self.assertIn("1 file", toolbox_text.done_text("download", 1))


class ToolboxWindow(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)

    def test_a_button_gives_its_action_and_copy_in_asks_for_the_folder(self):
        dialog = self.gui.toolbox_dialog.ToolboxDialog(FakeParent(), STATUS, admin=True)
        dialog._choose("copy_in")                               # no folder chosen: still open
        self.assertIsNone(dialog.result)
        replace(self, self.gui.toolbox_dialog.filedialog, "askdirectory", lambda **k: "C:/SOLIDWORKS Data")
        dialog._choose("copy_in")
        self.assertEqual(dialog.result, ("copy_in", "C:/SOLIDWORKS Data"))
        member = self.gui.toolbox_dialog.ToolboxDialog(FakeParent(), STATUS, admin=False)
        member._choose("download")
        self.assertEqual(member.result, ("download", None))

    def app(self, chosen, admin=True):
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: "/vault"
        app.identity = SimpleNamespace(allows=lambda action: (admin, "" if admin else "Only an Admin can do that."))
        self.tasks, self.said = [], []
        app.run_task = lambda work, text, on_success=None, **k: self.tasks.append((work, on_success, k.get("label")))
        app._say = lambda text, tone="normal": self.said.append(text)
        toolbox_admin = self.gui.team_admin.toolbox_admin
        replace(self, toolbox_admin, "status", lambda repo: STATUS)
        self.shown = []

        class Dialog:
            def __init__(inner, parent, status, may_change):
                self.shown.append(may_change)

            def show(inner):
                return chosen
        replace(self, self.gui.toolbox_dialog, "ToolboxDialog", Dialog)
        return app, toolbox_admin

    def test_the_chosen_action_runs_in_the_background(self):
        app, toolbox_admin = self.app(("upload", None))
        replace(self, toolbox_admin, "upload", lambda repo: {"added": 1, "changed": 0, "removed": 0})
        app.manage_toolbox(FakeParent())
        work, done, label = self.tasks[0]
        self.assertEqual((self.shown, label), ([True], "Uploading the team's Toolbox"))
        done(work())
        self.assertEqual(self.said[-1], "Team's Toolbox uploaded: 1 file added")

    def test_copy_in_asks_first(self):
        app, _toolbox_admin = self.app(("copy_in", "C:/SOLIDWORKS Data"))
        self.box.answer = False
        app.manage_toolbox(FakeParent())
        self.assertEqual(self.tasks, [])
        question = [c for c in self.box.calls if c[0] == "askokcancel"][0][1][1]
        self.assertIn("It replaces the team's Toolbox (1,844 files)", question)

    def test_closing_does_nothing(self):
        app, _toolbox_admin = self.app(None, admin=False)
        app.manage_toolbox(FakeParent())
        self.assertEqual((self.shown, self.tasks), ([False], []))


class VaultSettingsToolboxRule(unittest.TestCase):
    def test_the_rule_is_among_the_settings(self):
        gui = load_gui_with_fakes(FakeBox())
        dialog = gui.vault_settings_dialog.VaultSettingsDialog(FakeParent(), {"toolbox": toolbox_rules.TEAM,
                                                                            "assembly_variant_start": 500})
        self.assertEqual(dialog.toolbox_var.get(), "Only the team's Toolbox")
        dialog.toolbox_var.set("Don't check (default)")
        dialog._ok()
        self.assertEqual(dialog.result["toolbox"], toolbox_rules.OFF)


class AnotherToolboxOnThisComputer(unittest.TestCase):
    def setUp(self):
        self.gui = load_gui_with_fakes(FakeBox())
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.repo = lambda: "/vault"
        self.said = []
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        app._log = lambda text: None
        self.app = app
        module = self.gui.toolbox_setting
        replace(self, module.config, "get_toolbox_rule", lambda repo: toolbox_rules.TEAM)
        replace(self, module.cad_programs.DEFAULT, "library_folder", lambda: "C:\\SOLIDWORKS Data (2)\\")

    def test_said_once_a_session(self):
        self.app._check_toolbox_setting()
        self.app._check_toolbox_setting()
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.said[0][1], "warn")
        self.assertIn("not the team's", self.said[0][0])

    def test_nothing_when_it_uses_the_teams_or_the_rule_is_another(self):
        replace(self, self.gui.toolbox_setting.cad_programs.DEFAULT, "library_folder", lambda: "/vault/toolbox/")
        replace(self, self.gui.toolbox_setting.toolbox_admin, "tracked", lambda repo: [])
        self.app._check_toolbox_setting()
        self.assertEqual(self.said, [])
        self.app.__dict__.pop("_toolbox_setting_checked")
        replace(self, self.gui.toolbox_setting.config, "get_toolbox_rule", lambda repo: toolbox_rules.NO_TOOLBOX)
        replace(self, self.gui.toolbox_setting.cad_programs.DEFAULT, "library_folder", lambda: "C:\\Other")
        self.app._check_toolbox_setting()
        self.assertEqual(self.said, [])

    def test_the_teams_toolbox_not_downloaded_yet(self):
        module = self.gui.toolbox_setting
        replace(self, module.cad_programs.DEFAULT, "library_folder", lambda: "/vault/toolbox")
        replace(self, module.toolbox_admin, "tracked", lambda repo: ["toolbox/a.sldprt", "toolbox/b.sldprt"])
        replace(self, module.lfs_download, "stubs", lambda repo, rels: list(rels))
        self.app._check_toolbox_setting()
        self.assertEqual(self.said, [("2 files of the team's Toolbox are not downloaded yet, so SolidWorks can't use "
                                      "them. Download them in Team > Toolbox....", "warn")])


if __name__ == "__main__":
    unittest.main()
