"""Tests for core/toolbox_rules.py: the team's rule for SolidWorks Toolbox parts, and what it says about the files an
assembly uses that aren't Litterbox parts."""

import unittest

from litterbox.core import toolbox_rules as rules

SCREW = {"file": "C:\\SOLIDWORKS Data\\browser\\Ansi Inch\\socket head cap screw_ai.sldprt", "toolbox": True}
TEAM_NUT = {"file": "toolbox/browser/Ansi Inch/hex nut_ai.sldprt", "toolbox": True}
DESKTOP = {"file": "C:\\Users\\alex\\Desktop\\bracket.SLDPRT", "toolbox": False}
IN_VAULT = {"file": "documents/PROP-0001_A.SLDPRT", "toolbox": False}


class Checking(unittest.TestCase):
    def test_values(self):
        self.assertEqual(rules.check(None), rules.OFF)
        self.assertEqual(rules.check(" Team "), rules.TEAM)
        with self.assertRaises(rules.ToolboxRuleError):
            rules.check("sometimes")

    def test_where_a_file_is(self):
        self.assertFalse(rules.in_vault(SCREW["file"]))
        self.assertFalse(rules.in_vault("/home/alex/x.sldprt"))
        self.assertTrue(rules.in_vault(TEAM_NUT["file"]))
        self.assertTrue(rules.in_team_toolbox(TEAM_NUT["file"], "toolbox"))
        self.assertTrue(rules.in_team_toolbox("Toolbox\\browser\\x.sldprt", "toolbox"))
        self.assertFalse(rules.in_team_toolbox("toolboxes/x.sldprt", "toolbox"))
        self.assertFalse(rules.in_team_toolbox(SCREW["file"], "toolbox"))


class WhatEachRuleRefuses(unittest.TestCase):
    def test_off_refuses_nothing(self):
        self.assertEqual(rules.problems(rules.OFF, [SCREW, DESKTOP]), [])

    def test_no_toolbox_refuses_toolbox_parts_and_files_from_outside(self):
        found = rules.problems(rules.NO_TOOLBOX, [SCREW, TEAM_NUT, DESKTOP, IN_VAULT])
        self.assertEqual(len(found), 2)
        self.assertIn("(hex nut_ai.sldprt, socket head cap screw_ai.sldprt)", found[0])     # in order of name
        self.assertIn("doesn't use Toolbox", found[0])
        self.assertIn("bracket.SLDPRT", found[1])
        self.assertIn("C:\\Users\\alex\\Desktop", found[1])
        self.assertEqual(rules.problems(rules.NO_TOOLBOX, [IN_VAULT]), [])

    def test_team_takes_its_own_toolbox_only(self):
        self.assertEqual(rules.problems(rules.TEAM, [TEAM_NUT, IN_VAULT]), [])
        found = rules.problems(rules.TEAM, [SCREW, TEAM_NUT], toolbox_path="C:\\Litterbox\\hcr\\toolbox")
        self.assertEqual(len(found), 1)
        self.assertIn("aren't from the team's Toolbox (socket head cap screw_ai.sldprt", found[0])
        self.assertIn("C:\\SOLIDWORKS Data\\browser\\Ansi Inch", found[0])
        self.assertIn("set it to the team's at C:\\Litterbox\\hcr\\toolbox", found[0])
        self.assertIn("files from outside the vault", rules.problems(rules.TEAM, [DESKTOP])[0])

    def test_many_files_are_named_a_few_at_a_time(self):
        many = [{"file": f"C:\\SOLIDWORKS Data\\browser\\screw {n}.sldprt", "toolbox": True} for n in range(8)]
        self.assertIn("and 3 more", rules.problems(rules.NO_TOOLBOX, many)[0])


if __name__ == "__main__":
    unittest.main()
