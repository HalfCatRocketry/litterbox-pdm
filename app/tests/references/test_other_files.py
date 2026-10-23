"""Tests for reading the files an assembly uses that aren't Litterbox parts (reference_reader.read_other_files and the
check-in reader), with a pretend SolidWorks and no git."""

import os
import tempfile
import unittest
from pathlib import Path

from litterbox.core.part_number import PN
from litterbox.references import reference_reader
from tests.support import temp_folders

ASM = PN("HCR", 2, 500)


class FakeBackend:
    def __init__(self, repo, references, library=()):
        self.repo, self.refs, self.library = repo, references, list(library)

    def references(self, path):
        return self.refs

    def library_components(self, path):
        return self.library

    def components(self, path):
        return [(located, "counted") for _stored, located in self.refs if located]

    def close(self):
        pass


class ReadingOtherFiles(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.repo)
        for rel in ("cad/HCR-00002-500_A.SLDASM", "cad/HCR-00001-001_A.SLDPRT", "toolbox/browser/nut.sldprt"):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_bytes(b"x")
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.outside)
        self.screw = self.outside / "screw.sldprt"
        self.screw.write_bytes(b"x")
        self.desk = self.outside / "bracket.SLDPRT"
        self.desk.write_bytes(b"x")

    def full(self, rel):
        return os.path.join(str(self.repo), rel)

    def test_toolbox_parts_and_outside_files_but_not_the_vaults_own_parts(self):
        part, nut = self.full("cad/HCR-00001-001_A.SLDPRT"), self.full("toolbox/browser/nut.sldprt")
        backend = FakeBackend(self.repo, [(part, part), (nut, nut), (str(self.screw), str(self.screw)),
                                          ("D:/gone/missing.SLDPRT", ""), (str(self.desk), str(self.desk))],
                              library=[nut, str(self.screw)])
        found = reference_reader.read_other_files(self.repo, ASM, "A", backend, ["cad/HCR-00002-500_A.SLDASM"])
        self.assertEqual(found, sorted([{"file": str(self.desk), "toolbox": False},
                                        {"file": str(self.screw), "toolbox": True},
                                        {"file": "toolbox/browser/nut.sldprt", "toolbox": True}],
                                       key=lambda e: e["file"].lower()))
        self.assertEqual(reference_reader.vault_files_used(self.repo, ASM, "A", backend, ["cad/HCR-00002-500_A.SLDASM"]),
                         ["toolbox/browser/nut.sldprt"])

    def test_a_part_with_a_litterbox_name_outside_the_vault_counts_as_outside(self):
        copy = self.outside / "HCR-00001-001_A.SLDPRT"
        copy.write_bytes(b"x")
        backend = FakeBackend(self.repo, [(str(copy), str(copy))])
        found = reference_reader.read_other_files(self.repo, ASM, "A", backend, ["cad/HCR-00002-500_A.SLDASM"])
        self.assertEqual(found, [{"file": str(copy), "toolbox": False}])

    def test_vault_relative(self):
        self.assertEqual(reference_reader.vault_relative(self.repo, self.full("toolbox/a/b.sldprt")), "toolbox/a/b.sldprt")
        self.assertIsNone(reference_reader.vault_relative(self.repo, str(self.screw)))
        self.assertIsNone(reference_reader.vault_relative(self.repo, ""))

    def test_the_check_in_reader_gives_them_with_the_references(self):
        nut = self.full("toolbox/browser/nut.sldprt")
        backend = FakeBackend(self.repo, [(nut, nut)], library=[nut])
        read = reference_reader.make_reader(backend)(self.repo, ASM, "A", ["cad/HCR-00002-500_A.SLDASM"])
        self.assertEqual(read.other_files, [{"file": "toolbox/browser/nut.sldprt", "toolbox": True}])

    def test_if_they_cannot_be_read_the_rest_still_is(self):
        backend = FakeBackend(self.repo, [])
        backend.library_components = lambda path: (_ for _ in ()).throw(RuntimeError("busy"))
        logged = []
        read = reference_reader.make_reader(backend, log=logged.append)(self.repo, ASM, "A",
                                                                         ["cad/HCR-00002-500_A.SLDASM"])
        self.assertEqual((read.references, read.other_files), ([], None))
        self.assertIn("Toolbox", logged[-1])


if __name__ == "__main__":
    unittest.main()
