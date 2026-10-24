"""Tests for the Toolbox rule without git (parts/toolbox_check.py, the `toolbox` vault setting, and
team/guarded_push.toolbox_allowed); tests/vault/test_toolbox_flow.py tries them in a real vault."""

import unittest

import yaml

from litterbox import layout
from litterbox.core import toolbox_rules
from litterbox.errors import LitterboxError
from litterbox.git import repository
from litterbox.parts import toolbox_check
from litterbox.records import record_other_files
from litterbox.team import guarded_push
from litterbox.team import team_identity
from litterbox.vault import config
from litterbox.vault import config_write
from tests.support.gui_fakes import replace
from tests.support.registry_case import RegistryTestCase

SCREW = {"file": "C:\\SOLIDWORKS Data\\browser\\screw.sldprt", "toolbox": True}
NUT = {"file": "toolbox/browser/nut.sldprt", "toolbox": True}
FILES = ["cad/HCR-00042-500_A.SLDASM"]


class Setting(RegistryTestCase):
    def test_set_read_and_removed_and_a_rule_raises_the_vaults_minimum(self):
        self.assertEqual(config.get_toolbox_rule(self.repo), toolbox_rules.OFF)
        config_write.set_values(self.repo, toolbox="team")
        self.assertEqual(config.get_toolbox_rule(self.repo), toolbox_rules.TEAM)
        self.assertEqual(config.load(self.repo)["min_litterbox_version"], "0.6.0")
        config_write.set_values(self.repo, toolbox="")
        self.assertNotIn("toolbox", config.load(self.repo))
        with self.assertRaises(config.ConfigError):
            config_write.set_values(self.repo, toolbox="maybe")

    def test_a_bad_value_in_the_file_is_reported(self):
        path = self.repo / layout.CONFIG_PATH
        path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump({"toolbox": "lots"}), encoding="utf-8")
        with self.assertRaisesRegex(config.ConfigError, "toolbox in"):
            config.get_toolbox_rule(self.repo)


class Checks(RegistryTestCase):
    def setUp(self):
        super().setUp()
        self.record = self.make(42, variant=500)
        replace(self, repository, "tracked", lambda repo, pattern: ["toolbox/browser/Nut.sldprt"])

    def rule(self, value):
        config_write.set_values(self.repo, toolbox=value)

    def test_check_in(self):
        self.assertEqual(toolbox_check.check_in_problem(self.repo, self.record.pn, [SCREW]), "")     # no rule
        self.rule("none")
        self.assertEqual(toolbox_check.check_in_problem(self.repo, self.record.pn, None), "")     # not read
        refused = toolbox_check.check_in_problem(self.repo, self.record.pn, [SCREW])
        self.assertTrue(refused.startswith("HCR-00042-500 was not checked in. It uses Toolbox parts"))
        self.assertTrue(refused.endswith("It is still checked out to you."))

    def test_the_teams_toolbox_and_case(self):
        self.rule("team")
        self.assertEqual(toolbox_check.problems(self.repo, [NUT]), [])          # git has it (in any case)
        new = {"file": "toolbox/browser/bolt.sldprt", "toolbox": True}
        self.assertIn("not in the team's Toolbox yet (bolt.sldprt)", toolbox_check.problems(self.repo, [new])[0])
        self.assertIn("aren't from the team's Toolbox", toolbox_check.problems(self.repo, [SCREW])[0])

    def test_release(self):
        self.assertEqual(toolbox_check.release_problems(self.repo, self.record, "A", FILES), [])
        self.rule("none")
        self.assertIn("Update BOM", toolbox_check.release_problems(self.repo, self.record, "A", FILES)[0])
        self.assertEqual(toolbox_check.release_problems(self.repo, self.record, "A", ["cad/x_A.SLDPRT"]), [])
        record_other_files.set_other_files(self.record, [SCREW])
        self.assertIn("Toolbox parts", toolbox_check.release_problems(self.repo, self.record, "A", FILES)[0])
        record_other_files.set_other_files(self.record, [])
        self.assertEqual(toolbox_check.release_problems(self.repo, self.record, "A", FILES), [])


class OnlyAnAdminUploadsTheToolbox(unittest.TestCase):
    def changed(self, paths, allowed):
        replace(self, repository, "paths_changed_in", lambda repo, rev_range: set(paths))
        replace(self, team_identity, "current", lambda repo, probe=True: type(
            "Who", (), {"allows": lambda inner, action: (allowed, "" if allowed else "Only an Admin can do that.")})())

    def test_a_member_is_refused_only_when_the_toolbox_changed(self):
        self.changed(["cad/HCR-00001-001_A.SLDPRT", "PN-logs/HCR-00001-001.yaml"], allowed=False)
        guarded_push.toolbox_allowed("/vault")
        self.changed(["Toolbox/browser/nut.sldprt"], allowed=False)
        with self.assertRaisesRegex(LitterboxError, "Nothing was uploaded"):
            guarded_push.toolbox_allowed("/vault")
        self.changed(["toolbox/browser/nut.sldprt"], allowed=True)
        guarded_push.toolbox_allowed("/vault")


if __name__ == "__main__":
    unittest.main()
