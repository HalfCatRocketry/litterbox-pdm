"""Tests for where the vault keeps its templates and who changes them (vault/template_store.py,
vault/template_access.py): the index file read back, whose templates a change touches, and who may make it."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core import projects as project_rules
from litterbox.core import template_rules
from litterbox.team import team_identity
from litterbox.team import team_model
from litterbox.vault import template_access
from litterbox.vault import template_store

ROVER = project_rules.Project("Rover", "12", lead="bea", members=("cy",))


def templates():
    found = template_rules.added([], "HCR A.drwdot")
    found = template_rules.added(found, "HCR part.prtdot")
    return template_rules.added(found, "Rover A3.drwdot", "Rover")


def identity(person_id, access=team_model.MEMBER):
    person = team_model.Person(id=person_id, name=person_id.title(), access=access)
    return team_identity.Identity(team_identity.OK, person=person, directory=SimpleNamespace())


class Store(unittest.TestCase):
    def test_the_index_file_reads_back_as_it_was_written(self):
        with tempfile.TemporaryDirectory() as repo:
            self.assertEqual(template_store.load(repo), [])
            template_store.save(repo, templates())
            self.assertEqual(sorted(template_store.load(repo), key=lambda t: t.file),
                             sorted(templates(), key=lambda t: t.file))
            text = (Path(repo) / "templates" / "templates.yaml").read_text(encoding="utf-8")
            self.assertIn("project: Rover", text)
            self.assertEqual(template_store.path(repo, templates()[0]), Path(repo) / "templates" / "HCR A.drwdot")
            rover = template_rules.find(templates(), "Rover/Rover A3.drwdot")
            self.assertEqual(template_store.rel_path(rover), "templates/Rover/Rover A3.drwdot")

    def test_what_cant_be_read_is_left_out(self):
        self.assertEqual(template_store.parse("templates: [not, : valid"), [])
        read = template_store.parse("templates:\n- {file: notes.txt}\n- oops\n- {file: A.drwdot}\n"
                                    "- {file: a.DRWDOT, default: true}\n")
        self.assertEqual([(t.file, t.default) for t in read], [("A.drwdot", True)])     # the first, made the default

    def test_whose_templates_a_change_touches(self):
        before = templates()
        after = template_rules.made_default(template_rules.added(before, "HCR B.drwdot"), "HCR B.drwdot")
        self.assertEqual(template_store.changed_owners(before, after, ["templates/HCR B.drwdot",
                                                                       "templates/templates.yaml"]), {""})
        moved = template_rules.renamed_project(before, "Rover", "Rover 2")
        self.assertEqual(template_store.changed_owners(before, moved, []), {"Rover", "Rover 2"})
        self.assertEqual(template_store.changed_owners(before, before, ["templates/Rover/Rover A3.drwdot"]), {"Rover"})
        self.assertEqual(template_store.changed_owners(before, before, ["templates/Rover/notes.txt"]), {"Rover"})
        self.assertEqual(template_store.changed_owners(before, before, ["templates/stray.bin", "cad/x.SLDPRT"]), {""})
        self.assertEqual(template_store.changed_owners(before, before, ["templates/Elsewhere/x.drwdot"]), {""})
        self.assertEqual(template_store.changed_owners(before, before, ["templates/templates.yaml"]), set())


class Access(unittest.TestCase):
    def test_who_changes_which(self):
        admin, bea, cy = identity("alex", team_model.ADMIN), identity("bea"), identity("cy")
        self.assertEqual(template_access.may_change(admin), (True, ""))
        self.assertEqual(template_access.may_change(admin, ROVER), (True, ""))
        self.assertIn("Only Admins and the Owner", template_access.may_change(bea)[1])
        self.assertEqual(template_access.may_change(bea, ROVER), (True, ""))                 # its Lead
        self.assertIn("Only Rover's Lead", template_access.may_change(cy, ROVER)[1])          # a member
        legacy = team_identity.Identity(team_identity.LEGACY)
        self.assertEqual(template_access.may_change(legacy), (True, ""))

    def test_an_upload_is_checked_for_each_owner(self):
        bea = identity("bea")
        self.assertEqual(template_access.check_upload({"Rover"}, bea, [ROVER]), [])
        self.assertEqual(len(template_access.check_upload({"", "Rover"}, bea, [ROVER])), 1)
        self.assertEqual(template_access.check_upload({"Gone"}, bea, [ROVER]), [])         # no project to guard


if __name__ == "__main__":
    unittest.main()
