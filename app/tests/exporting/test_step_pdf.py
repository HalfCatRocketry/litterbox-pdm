"""Tests for making STEP and PDF files (exporting/step_pdf.py) with a stand-in for SolidWorks. No git: a vault
folder with records and files is enough."""

import os
import stat
import unittest

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.exporting import step_pdf
from litterbox.records import record_store
from tests.exporting.test_part_files_export import temporary_folder

PART, ASM, BARE = PN("HCR", 1, 1), PN("HCR", 2, 1), PN("HCR", 3, 1)
BOTH = [step_pdf.STEP, step_pdf.PDF]


class FakeSolidWorks:
    """Writes a small file for each save, and remembers what it was asked. `broken` names files it fails on."""

    def __init__(self, broken=()):
        self.saved, self.closed, self.broken = [], False, set(broken)

    def _save(self, kind, path, out):
        name = os.path.basename(path)
        if name in self.broken:
            raise RuntimeError(f"(-2147023170, 'The remote procedure call failed.') on {name}")
        self.saved.append((kind, name, os.path.basename(out)))
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"{kind} of {name}\n")

    def save_step(self, path, out):
        self._save("STEP", path, out)

    def save_pdf(self, path, out):
        self._save("PDF", path, out)

    def version(self):
        return "32.5.0"

    def close(self):
        self.closed = True


class StepPdf(unittest.TestCase):
    def setUp(self):
        self.tmp = temporary_folder(self)
        self.repo, self.out = self.tmp / "vault", self.tmp / "out"
        (self.repo / "cad").mkdir(parents=True)
        self.out.mkdir()
        for pn, name in ((PART, "Bracket"), (ASM, "Frame"), (BARE, "Nothing yet")):
            record_store.create_record(self.repo, pn, name, "Alex")
        record = record_store.load(self.repo, PART)
        record.revision, record.released_revision = "B", "A"
        record_store.save(self.repo, record)
        for name in ("HCR-00001-001_A.SLDPRT", "HCR-00001-001_B.SLDPRT", "HCR-00001-001_B.SLDDRW",
                     "HCR-00002-001_A.SLDASM", "HCR-00002-001_A.stp"):
            (self.repo / "cad" / name).write_text(f"contents of {name}\n", encoding="utf-8")
        self.sw = FakeSolidWorks()

    def make(self, jobs, folder=None, sw=None):
        sw = sw or self.sw
        return step_pdf.make(self.repo, jobs, folder or self.out, backend_factory=lambda: sw)

    def test_the_working_revision_is_used_and_kinds_follow_the_files(self):
        jobs, notes = step_pdf.jobs_for(self.repo, [PART, ASM, BARE], BOTH)
        self.assertEqual([(str(j.pn), j.revision, j.kinds) for j in jobs],
                         [("HCR-00001-001", "B", BOTH), ("HCR-00002-001", "A", [step_pdf.STEP])])
        self.assertEqual(jobs[0].sources, {step_pdf.STEP: "cad/HCR-00001-001_B.SLDPRT",
                                           step_pdf.PDF: "cad/HCR-00001-001_B.SLDDRW"})
        self.assertEqual(notes, ["HCR-00002-001 Rev A has no drawing, so it gets no PDF.",
                                 "HCR-00003-001 Rev A has no model or drawing."])

    def test_choose_at_least_one_kind(self):
        with self.assertRaisesRegex(LitterboxError, "STEP, PDF or both"):
            step_pdf.jobs_for(self.repo, [PART], [])

    def test_outside_the_vault_files_get_litterbox_names(self):
        jobs, _notes = step_pdf.jobs_for(self.repo, [PART, ASM], BOTH)
        made = self.make(jobs)
        self.assertEqual(sorted(os.listdir(self.out)), ["HCR-00001-001_B.PDF", "HCR-00001-001_B.STEP",
                                                        "HCR-00002-001_A.STEP"])
        self.assertEqual(made.made[PART][step_pdf.STEP]["file"], "HCR-00001-001_B.STEP")
        self.assertEqual(list(made.made[PART][step_pdf.PDF]["from"]), ["cad/HCR-00001-001_B.SLDDRW"])
        self.assertEqual(made.made[PART][step_pdf.PDF]["solidworks"], "32.5.0")
        self.assertTrue(self.sw.closed)
        self.assertEqual(made.errors, {})

    def test_in_the_vault_an_old_stp_is_replaced_under_its_own_name(self):
        jobs, _notes = step_pdf.jobs_for(self.repo, [ASM], BOTH, in_vault=True)
        self.assertEqual(jobs[0].names, {step_pdf.STEP: "HCR-00002-001_A.stp"})
        target = self.repo / "cad" / "HCR-00002-001_A.stp"
        os.chmod(target, stat.S_IREAD)                      # someone else's file in a vault is read-only
        self.make(jobs, self.repo / "cad")
        self.assertEqual(target.read_text(encoding="utf-8"), "STEP of HCR-00002-001_A.SLDASM\n")
        self.assertFalse((self.repo / "cad" / "HCR-00002-001_A.STEP").exists())

    def test_a_failure_is_reported_for_its_part_and_the_rest_carry_on(self):
        sw = FakeSolidWorks(broken={"HCR-00001-001_B.SLDDRW"})
        jobs, _notes = step_pdf.jobs_for(self.repo, [PART, ASM], BOTH)
        made = self.make(jobs, sw=sw)
        self.assertIn("could not make HCR-00001-001_B.PDF", made.errors[PART])
        self.assertEqual(list(made.made[PART]), [step_pdf.STEP])       # its STEP was still made
        self.assertIn(ASM, made.made)
        self.assertFalse((self.out / "HCR-00001-001_B.PDF").exists())
        self.assertTrue(sw.closed)

    def test_nothing_to_make_never_starts_solidworks(self):
        started = []
        made = step_pdf.make(self.repo, [], self.out, backend_factory=lambda: started.append(1))
        self.assertEqual((made.made, made.errors, started), ({}, {}, []))


if __name__ == "__main__":
    unittest.main()
