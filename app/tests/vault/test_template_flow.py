"""Tests for the vault's SolidWorks templates in a real vault (vault/template_admin.py, team/guarded_push.
templates_allowed, parts/from_template.py): Admins and the Owner change the org's templates, a project's Lead its
own, nobody else's upload of a template change gets through, a renamed project keeps its templates, and a part's
model and drawing are made from them. Alex is the Owner; Bea leads project Rover and Cy is in it. A stand-in for
SolidWorks makes the files, so these run without it (and need Linux, macOS or WSL, as git tests do)."""

import tempfile
import unittest
from pathlib import Path

from tests.support import temp_folders
from tests.support.vault_fixture import git
from tests.support.workflow_fixture import Fixture

from litterbox.core import file_types
from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import from_template
from litterbox.team import guarded_push
from litterbox.vault import project_admin
from litterbox.vault import template_admin
from litterbox.vault import template_store

NEW = PN("HCR", 7, 1)


class FakeSolidWorks:
    """Makes a "file" from a template: the template's bytes and a mark, so a test can tell which was used."""

    def __init__(self):
        self.made = []

    def new_from_template(self, template, out):
        Path(out).write_bytes(Path(template).read_bytes() + b" made")
        self.made.append((Path(template).name, Path(out).name))

    def close(self):
        pass


class Templates(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        source = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, source)
        self.files = {}
        for name in ("HCR A.drwdot", "HCR part.prtdot", "Rover A3.drwdot", "Cy.drwdot"):
            (source / name).write_bytes(name.encode())
            self.files[name] = source / name
        with self.user("Alex"):
            project_admin.add_project(self.a, "Rover", "12", team={"lead": "bea", "members": ["cy"]})

    def names(self, user):
        return {(t.file, t.project, t.default) for t in template_store.load(self.repo_of(user))}

    def test_the_owner_adds_the_orgs_and_everyone_gets_them(self):
        self.do("Alex", template_admin.add, self.files["HCR A.drwdot"])
        self.do("Alex", template_admin.add, self.files["HCR part.prtdot"])
        self.assertIn("Templates: HCR A added for the org", self.remote_log())
        self.get_latest("Bea")
        self.assertEqual(self.names("Bea"), {("HCR A.drwdot", "", True), ("HCR part.prtdot", "", True)})
        self.assertEqual((self.b / "templates" / "HCR A.drwdot").read_bytes(), b"HCR A.drwdot")
        with self.assertRaisesRegex(LitterboxError, "already has a template called HCR A.drwdot"):
            self.do("Alex", template_admin.add, self.files["HCR A.drwdot"])

    def test_a_member_cant_change_the_orgs(self):
        with self.assertRaisesRegex(LitterboxError, "Only Admins and the Owner change the org's templates"):
            self.do("Bea", template_admin.add, self.files["HCR A.drwdot"])
        self.assertFalse((self.b / "templates").exists())

    def test_a_projects_lead_changes_its_templates_and_its_members_dont(self):
        self.get_latest("Bea")
        self.do("Bea", template_admin.add, self.files["Rover A3.drwdot"], "Rover")
        self.assertIn("Templates: Rover A3 added for project Rover", self.remote_log())
        self.assertTrue((self.b / "templates" / "Rover" / "Rover A3.drwdot").is_file())       # the project's folder
        self.get_latest("Cy")
        with self.assertRaisesRegex(LitterboxError, "Only Rover's Lead, Admins and the Owner"):
            self.do("Cy", template_admin.add, self.files["Cy.drwdot"], "Rover")
        with self.assertRaisesRegex(LitterboxError, "Only Rover's Lead"):
            self.do("Cy", template_admin.remove, "Rover/Rover A3.drwdot")

    def test_a_change_made_by_hand_is_refused_at_upload(self):
        self.do("Alex", template_admin.add, self.files["HCR A.drwdot"])
        self.get_latest("Cy")
        index = self.c / "templates" / "templates.yaml"
        index.write_text(index.read_text(encoding="utf-8").replace("HCR A.drwdot", "Mine.drwdot"), encoding="utf-8")
        git(self.c, "commit", "-am", "My own template list")
        with self.assertRaisesRegex(LitterboxError, "template changes you may not make. Only Admins and the Owner"):
            self.do("Cy", guarded_push.push)
        self.assertNotIn("My own template list", self.remote_log())

    def test_the_default_and_removing_and_a_renamed_project(self):
        self.do("Alex", template_admin.add, self.files["HCR A.drwdot"])
        self.do("Alex", template_admin.add, self.files["Rover A3.drwdot"], "Rover")
        self.do("Alex", template_admin.add, self.files["Cy.drwdot"], "Rover")
        self.do("Alex", template_admin.make_default, "Rover/Cy.drwdot")
        self.assertIn(("Cy.drwdot", "Rover", True), self.names("Alex"))
        self.do("Alex", template_admin.remove, "Rover/Cy.drwdot")
        self.assertIn(("Rover A3.drwdot", "Rover", True), self.names("Alex"))           # the default passes on
        self.assertFalse((self.a / "templates" / "Rover" / "Cy.drwdot").exists())
        self.assertNotIn("templates/Rover/Cy.drwdot", git(self.a, "ls-files", "templates").splitlines())
        self.do("Alex", project_admin.edit_project, "Rover", "Rover 2", "12")
        self.assertIn(("Rover A3.drwdot", "Rover 2", True), self.names("Alex"))
        self.assertIn("Templates: project Rover renamed to Rover 2", self.remote_log())
        self.assertEqual(git(self.a, "ls-files", "templates").splitlines(),
                         ["templates/HCR A.drwdot", "templates/Rover 2/Rover A3.drwdot", "templates/templates.yaml"])
        self.assertFalse((self.a / "templates" / "Rover").exists())
        self.assertEqual(git(self.a, "status", "--porcelain"), "")
        self.get_latest("Bea")
        self.assertTrue((self.b / "templates" / "Rover 2" / "Rover A3.drwdot").is_file())

    def test_a_parts_model_and_drawing_are_made_from_templates(self):
        self.do("Alex", template_admin.add, self.files["HCR A.drwdot"])
        self.do("Alex", template_admin.add, self.files["HCR part.prtdot"])
        self.add_created_part(7)
        self.do("Alex", checkout.checkout, NEW)
        self.assertEqual(self.do("Alex", from_template.wanted_kinds, NEW), from_template.MODEL_KINDS)
        self.assertEqual(self.do("Alex", from_template.default_template, NEW, file_types.PART).file, "HCR part.prtdot")
        sw = FakeSolidWorks()
        with self.assertRaisesRegex(LitterboxError, "has no model yet"):
            self.do("Alex", from_template.make, NEW, "HCR A.drwdot", backend=sw, log=lambda _text: None)
        model = self.do("Alex", from_template.make, NEW, "HCR part.prtdot", backend=sw, log=lambda _text: None)
        self.assertEqual(model, "cad/HCR-00007-001_A.SLDPRT")
        drawing = self.do("Alex", from_template.make, NEW, "HCR A.drwdot", backend=sw, log=lambda _text: None)
        self.assertEqual((self.a / drawing).read_bytes(), b"HCR A.drwdot made")
        self.assertEqual(self.do("Alex", from_template.wanted_kinds, NEW), ())
        with self.assertRaisesRegex(LitterboxError, "has a drawing already"):
            self.do("Alex", from_template.make, NEW, "HCR A.drwdot", backend=sw, log=lambda _text: None)
        self.do("Alex", checkin.checkin, NEW, "First model and drawing")
        self.assertEqual(sorted(git(self.a, "ls-files", "cad/HCR-00007-001_*").splitlines()),
                         ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"])


if __name__ == "__main__":
    unittest.main()
