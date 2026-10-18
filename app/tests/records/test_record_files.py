"""Tests for records/record_files.py: which CAD files belong to a part."""

import unittest
from litterbox.records import record_files
from litterbox.records import record_store
from litterbox.core.part_number import PN
from tests.support.registry_case import RegistryTestCase


class TestCadFiles(RegistryTestCase):
    def test_finds_only_files_for_that_pn(self):
        cad = self.repo / "cad"
        cad.mkdir()
        for name in ("HCR-00042-001_A.SLDPRT", "HCR-00042-001_A.SLDDRW", "HCR-00042-002_A.SLDPRT",
                     "~$HCR-00042-001_A.SLDPRT", "notes.txt", "hcr-00043-001.sldprt"):
            (cad / name).write_bytes(b"x")
        (cad / "HCR-00042-001.folder").mkdir()
        self.assertEqual(record_files.cad_files(self.repo, PN("HCR", 42, 1), "A"),
                         ["cad/HCR-00042-001_A.SLDDRW", "cad/HCR-00042-001_A.SLDPRT"])
        self.assertEqual(record_files.cad_files(self.repo, PN("HCR", 43, 1), "A"), [])   # no revision on the name: not ours
        self.assertEqual(record_files.cad_files(self.repo, PN("HCR", 99, 1), "A"), [])
        self.assertEqual(record_files.cad_files(self.repo, PN("HCR", 42, 1), "B"), [])

    def test_cad_index_groups_every_pn_in_one_scan(self):
        cad = self.repo / "cad"
        cad.mkdir()
        for name in ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW", "HCR-00002-001_A.SLDPRT", "junk.txt"):
            (cad / name).write_bytes(b"x")
        index = record_files.cad_index(self.repo)
        self.assertEqual(index, {
            PN("HCR", 1, 1): {"A": ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]},
            PN("HCR", 2, 1): {"A": ["cad/HCR-00002-001_A.SLDPRT"]},
        })
        self.assertEqual(record_files.cad_index(self.repo / "nowhere"), {})

    def test_every_revision_is_indexed_and_the_working_one_is_the_default(self):
        cad = self.repo / "cad"
        cad.mkdir()
        record = self.make(5)
        for name in ("HCR-00005-001_A.SLDPRT", "HCR-00005-001_B.SLDPRT", "HCR-00005-001_B.SLDDRW"):
            (cad / name).write_bytes(b"x")
        self.assertEqual(sorted(record_files.cad_index(self.repo)[record.pn]), ["A", "B"])
        self.assertEqual(record_files.cad_files(self.repo, record.pn), ["cad/HCR-00005-001_A.SLDPRT"])   # working is A
        record.revision = "B"
        path = self.repo / "PN-logs" / "HCR-00005-001.yaml"
        path.chmod(0o644)
        record_store.save(self.repo, record)
        self.assertEqual(len(record_files.cad_files(self.repo, record.pn)), 2)
        self.assertEqual(len(record_files.all_cad_files(self.repo, record.pn)), 3)

    def test_missing_cad_folder(self):
        self.assertEqual(record_files.cad_files(self.repo, PN("HCR", 1, 1), "A"), [])


if __name__ == "__main__":
    unittest.main()
