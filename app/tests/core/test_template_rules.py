"""Tests for the SolidWorks templates' rules (core/template_rules.py): one default in every group, a project's
templates before the org's, and the template a part gets."""

import unittest

from litterbox.core import file_types
from litterbox.core import template_rules
from litterbox.core.template_rules import ORG, Template, TemplateError

DRAWING, PART, ASSEMBLY = file_types.DRAWING, file_types.PART, file_types.ASSEMBLY


def vault():
    templates = []
    for file, project in (("HCR B.drwdot", ORG), ("HCR A.drwdot", ORG), ("HCR part.prtdot", ORG),
                          ("Rover A3.drwdot", "Rover")):
        templates = template_rules.added(templates, file, project)
    return templates


class Kinds(unittest.TestCase):
    def test_what_a_template_makes(self):
        self.assertEqual(file_types.template_kind("x/HCR A.DRWDOT"), DRAWING)
        self.assertEqual(file_types.template_kind("Part.prtdot"), PART)
        self.assertEqual(file_types.template_kind("Assembly.asmdot"), ASSEMBLY)
        self.assertIsNone(file_types.template_kind("a - landscape.slddrt"))         # a sheet format isn't one
        self.assertEqual(file_types.made_from("A.drwdot"), ".slddrw")
        self.assertEqual(file_types.made_from("A.asmdot"), ".sldasm")
        self.assertEqual(file_types.made_from("A.slddrw"), "")
        self.assertEqual(file_types.template_program("A.prtdot"), "SolidWorks")


class Rules(unittest.TestCase):
    def test_the_first_of_each_kind_and_owner_is_the_default(self):
        templates = vault()
        defaults = sorted(t.file for t in templates if t.default)
        self.assertEqual(defaults, ["HCR B.drwdot", "HCR part.prtdot", "Rover A3.drwdot"])
        self.assertEqual(template_rules.find(templates, "hcr a.DRWDOT").name, "HCR A")

    def test_a_project_part_gets_its_projects_default_then_the_orgs(self):
        templates = vault()
        self.assertEqual([t.file for t in template_rules.choices(templates, DRAWING, "rover")],
                         ["Rover A3.drwdot", "HCR B.drwdot", "HCR A.drwdot"])
        self.assertEqual(template_rules.default_for(templates, DRAWING, "Rover").file, "Rover A3.drwdot")
        self.assertEqual(template_rules.default_for(templates, PART, "Rover").file, "HCR part.prtdot")   # none of its own
        self.assertEqual([t.file for t in template_rules.choices(templates, DRAWING)], ["HCR B.drwdot", "HCR A.drwdot"])
        self.assertIsNone(template_rules.default_for(templates, ASSEMBLY, "Rover"))

    def test_changing_the_default_and_removing_it(self):
        templates = template_rules.made_default(vault(), "HCR A.drwdot")
        self.assertEqual(template_rules.default_for(templates, DRAWING).file, "HCR A.drwdot")
        self.assertTrue(template_rules.find(templates, "Rover A3.drwdot").default)        # another group: untouched
        templates = template_rules.removed(templates, "HCR A.drwdot")
        self.assertEqual(template_rules.default_for(templates, DRAWING).file, "HCR B.drwdot")    # the next one
        with self.assertRaises(TemplateError):
            template_rules.removed(templates, "HCR A.drwdot")
        with self.assertRaises(TemplateError):
            template_rules.made_default(templates, "gone.drwdot")

    def test_names_are_shared_by_the_org_and_every_project(self):
        with self.assertRaisesRegex(TemplateError, "already has a template called HCR A.drwdot \\(for the org\\)"):
            template_rules.added(vault(), "hcr a.drwdot", "Rover")
        for bad in ("notes.txt", "a - landscape.slddrt", "", "x/y.drwdot", "a:b.prtdot", ".drwdot"):
            with self.assertRaises(TemplateError):
                template_rules.check_file_name(bad)

    def test_one_default_whatever_the_file_said(self):
        loose = [Template("B.drwdot", DRAWING, default=True), Template("A.drwdot", DRAWING, default=True),
                 Template("C.prtdot", PART)]
        fixed = template_rules.normalized(loose)
        self.assertEqual([t.default for t in fixed], [False, True, True])

    def test_a_renamed_project_keeps_its_templates(self):
        templates = template_rules.renamed_project(vault(), "rover", "Rover 2")
        self.assertEqual(template_rules.default_for(templates, DRAWING, "Rover 2").file, "Rover A3.drwdot")
        self.assertEqual(template_rules.find(templates, "HCR A.drwdot").project, ORG)


if __name__ == "__main__":
    unittest.main()
