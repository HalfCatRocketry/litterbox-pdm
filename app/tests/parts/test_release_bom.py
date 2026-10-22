"""Tests for the BOM kept with a released assembly revision (parts/release_bom.py). Which parts get one needs no git;
the flow runs against real git repos with a fake git-lfs (skipped on Windows unless LITTERBOX_GIT_TESTS=1)."""

import unittest

from litterbox.core.part_number import PN
from litterbox.parts import generate_files
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import release_bom
from litterbox.parts import revise
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from tests.exporting.test_step_pdf import FakeSolidWorks
from tests.support.references_fixture import ASM, RefsFixture

BOM = "cad/HCR-00002-001_A_BOM.csv"


class Wanted(unittest.TestCase):
    def test_only_a_released_cad_assembly_gets_one(self):
        record = record_model.Record(ASM, "Frame", "Alex", "t", references={"A": ["HCR-00001-001_A"]})
        self.assertFalse(release_bom.wanted(record))                            # not released yet
        record_lifecycle.mark_released(record, "Alex", ["cad/HCR-00002-001_A.SLDASM"])
        self.assertTrue(release_bom.wanted(record))
        record.kind = record_model.KIND_NONCAD
        self.assertFalse(release_bom.wanted(record))                            # a kit keeps no files in cad/
        part = record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "t")
        record_lifecycle.mark_released(part, "Alex", ["cad/HCR-00001-001_A.SLDPRT"])
        self.assertFalse(release_bom.wanted(part))                              # uses no other parts
        self.assertEqual(release_bom.bom_path(ASM, "A"), BOM)


class ReleaseBomFlow(RefsFixture, unittest.TestCase):
    def test_a_released_assembly_keeps_its_bom_and_still_gets_its_step(self):
        sw = FakeSolidWorks()
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)
            result = generate_files.after_release(self.a, [ASM], backend_factory=lambda: sw)
            self.assertEqual((result.boms, result.bom_failed), ([(ASM, BOM)], []))
            self.assertEqual([pn for pn, _files in result.done], [ASM])         # the STEP wasn't skipped
            self.assertIn("HCR-00002-001: BOM saved with the release", git_log(self))
            self.assertEqual(self.locks(self.a), {})
            events = [(e["event"], e.get("files")) for e in self.record().history[-2:]]
            self.assertEqual(events[0], ("files_made", [BOM]))
            self.assertIn(BOM, record_files.cad_index(self.a)[ASM]["A"])
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            text = (self.b / BOM).read_text(encoding="utf-8-sig")
            self.assertIn("HCR-00001-001", text)
            self.assertIn("Total cost", text)
        with self.user("Alex"):                                                 # Revise leaves it with Rev A
            revise.revise(self.a, ASM, "Next", backend=self.fake, log=lambda *_: None)
            self.assertFalse((self.a / BOM.replace("_A_", "_B_")).exists())
            self.assertTrue((self.a / BOM).exists())

    def test_a_part_released_earlier_is_left_alone(self):
        with self.user("Alex"):
            result = generate_files.after_release(self.a, [ASM], backend_factory=FakeSolidWorks)
            self.assertEqual(result.boms, [])
            self.assertFalse((self.a / BOM).exists())


def git_log(case):
    from tests.support.vault_fixture import git
    return git(case.a, "log", "--format=%B", "origin/main")
