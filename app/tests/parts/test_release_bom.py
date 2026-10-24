"""Tests for the BOM kept with a released assembly revision (parts/release_bom.py). Which parts get one needs no git;
the flow runs against real git repos with a fake git-lfs (skipped on Windows unless LITTERBOX_GIT_TESTS=1)."""

import unittest

from litterbox.core.part_number import PN
from litterbox.parts import generate_files
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.parts import release_bom
from litterbox.parts import part_status
from litterbox.parts import revise
from litterbox.records import record_exports
from litterbox.records import record_files
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from tests.exporting.test_step_pdf import FakeSolidWorks
from tests.support.references_fixture import ASM, RefsFixture
from tests.support.vault_fixture import git

BOM = "cad/HCR-00002-001_A_BOM.csv"
KIT = PN("HCR", 3, 500)
PART_1 = PN("HCR", 1, 1)
KIT_BOM = "cad/HCR-00003-500_A_BOM.csv"


class Wanted(unittest.TestCase):
    def test_a_released_assembly_or_kit_gets_one_and_is_flagged_until_then(self):
        record = record_model.Record(ASM, "Frame", "Alex", "t", references={"A": ["HCR-00001-001_A"]})
        self.assertFalse(release_bom.wanted(record))                            # not released yet
        record_lifecycle.mark_released(record, "Alex", ["cad/HCR-00002-001_A.SLDASM"])
        self.assertTrue(release_bom.wanted(record))
        self.assertTrue(record_exports.bom_flagged(record))                     # until it is saved
        record_exports.bom_saved(record, "A")
        self.assertFalse(record_exports.bom_flagged(record))
        self.assertEqual(record.exports["A"], {"wanted": True})                 # the STEP/PDF flag stays
        kit = record_model.Record(KIT, "Fastener kit", "Alex", "t", kind=record_model.KIND_NONCAD,
                                  bom_items={"A": {"HCR-00001-001_A": 4}})
        record_lifecycle.mark_released(kit, "Alex", [])
        self.assertTrue(release_bom.wanted(kit))                                # a kit too
        self.assertEqual(kit.exports, {"A": {"bom_wanted": True}})              # no STEP or PDF for a kit
        record_exports.bom_saved(kit, "A")
        self.assertEqual(kit.exports, {})
        part = record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "t")
        record_lifecycle.mark_released(part, "Alex", ["cad/HCR-00001-001_A.SLDPRT"])
        self.assertFalse(release_bom.wanted(part))                              # uses no other parts
        self.assertFalse(record_exports.bom_flagged(part))
        self.assertEqual(release_bom.bom_path(ASM, "A"), BOM)

    def test_a_release_from_before_the_flag_is_never_flagged(self):
        record = record_model.Record(ASM, "Frame", "Alex", "t", references={"A": ["HCR-00001-001_A"]},
                                     status=record_model.STATUS_RELEASED, released_revision="A")
        self.assertTrue(release_bom.wanted(record))
        self.assertFalse(record_exports.bom_flagged(record))


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

    def test_a_bom_not_saved_with_the_release_is_flagged_and_saved_later_once(self):
        with self.user("Alex"):
            lifecycle.release(self.a, ASM)                  # as if the BOM's upload had failed after the release
            row = next(r for r in part_status.get_status(self.a) if r.pn == ASM)
            self.assertTrue(row.bom_file_needed)
            self.assertIn("(BOM file needs saving)", row.state)
            done, failed = release_bom.save(self.a, [ASM, PART_1], later=True)
            self.assertEqual(done, [(ASM, BOM)])
            self.assertEqual(failed, [(PART_1, "It has no BOM: it isn't an assembly or a kit.")])
            self.assertIn("HCR-00002-001: BOM saved", git_log(self))
            self.assertFalse(record_exports.bom_flagged(self.record()))
            self.assertNotIn("(BOM file", next(r for r in part_status.get_status(self.a) if r.pn == ASM).state)
            done, failed = release_bom.save(self.a, [ASM], later=True)              # never over the saved one
            self.assertEqual((done, failed), ([], [(ASM, "Rev A's BOM was saved with its release already.")]))

    def test_a_kit_gets_its_bom_saved_at_release(self):
        with self.user("Alex"):
            record_store.create_record(self.a, KIT, "Fastener kit", "Alex", kind=record_model.KIND_NONCAD)
            kit = record_store.load(self.a, KIT)
            kit.bom_items = {"A": {"HCR-00001-001_A": 4}}
            record_store.save(self.a, kit)
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "A kit")
            git(self.a, "push")
            lifecycle.release(self.a, KIT)
            result = generate_files.after_release(self.a, [KIT], backend_factory=FakeSolidWorks)
            self.assertEqual((result.boms, result.bom_failed, result.done), ([(KIT, KIT_BOM)], [], []))
            self.assertIn("HCR-00001-001", (self.a / KIT_BOM).read_text(encoding="utf-8-sig"))
            row = next(r for r in part_status.get_status(self.a) if r.pn == KIT)
            self.assertEqual((row.kind, row.files, row.bom_file_needed), ("released", [KIT_BOM], False))

    def test_a_part_released_earlier_is_left_alone(self):
        with self.user("Alex"):
            result = generate_files.after_release(self.a, [ASM], backend_factory=FakeSolidWorks)
            self.assertEqual(result.boms, [])
            self.assertFalse((self.a / BOM).exists())


def git_log(case):
    from tests.support.vault_fixture import git
    return git(case.a, "log", "--format=%B", "origin/main")
