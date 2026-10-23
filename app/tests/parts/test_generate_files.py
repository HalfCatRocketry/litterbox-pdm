"""Tests for Generate STEP/PDF in the vault and after a release (parts/generate_files.py). The rules need no git;
the flows run against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they
need Linux, macOS or WSL and are skipped on Windows. SolidWorks is a stand-in (tests/exporting/test_step_pdf.py)."""

import unittest

from litterbox.core.part_number import PN
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import generate_files
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from litterbox.records import record_exports
from litterbox.records import record_lifecycle
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.team import team_model
from tests.exporting.test_step_pdf import FakeSolidWorks
from tests.support.engine_fixture import EngineFixture
from tests.support.vault_fixture import PART, REC, SKIP_ON_WINDOWS, git, is_writable

BOTH = list(record_exports.KINDS)
FILES = ["cad/HCR-00001-001_A.SLDDRW", "cad/HCR-00001-001_A.SLDPRT"]
STEP, PDF = "cad/HCR-00001-001_A.STEP", "cad/HCR-00001-001_A.PDF"


def record(status="in_work"):
    r = record_model.Record(PN("HCR", 1, 1), "Bracket", "Alex", "2026-10-21T10:00:00Z")
    if status == "released":
        record_lifecycle.mark_released(r, "Alex", FILES)
    return r


class Refusal(unittest.TestCase):
    def test_parts_nobody_has_and_your_own_are_fine(self):
        self.assertEqual(generate_files.refusal(record(), None, False, FILES), "")
        self.assertEqual(generate_files.refusal(record(), ("you", "Alex"), True, FILES), "")

    def test_what_stops_it(self):
        void = record()
        void.status = "void"
        pending = record()
        pending.pending = {"id": "b1"}
        self.assertIn("void", generate_files.refusal(void, None, False, FILES))
        self.assertIn("sign-offs", generate_files.refusal(pending, None, False, FILES))
        self.assertIn("checked out by Bea", generate_files.refusal(record(), ("other", "Bea"), False, FILES))
        self.assertIn("not checked in", generate_files.refusal(record(), None, True, FILES))

    def test_a_released_part_takes_them_while_flagged_or_missing(self):
        r = record("released")
        self.assertEqual(generate_files.refusal(r, None, False, FILES + [STEP, PDF]), "")     # flagged
        r.exports["A"] = {"step": {"file": STEP}, "pdf": {"file": PDF}}                       # made since
        self.assertIn("up to date", generate_files.refusal(r, None, False, FILES + [STEP, PDF]))
        self.assertEqual(generate_files.refusal(r, None, False, FILES + [STEP]), "")          # its PDF is missing
        self.assertEqual(generate_files.refusal(r, None, False, FILES + [STEP, PDF], force=True), "")

    def test_making_them_again_is_for_admins_and_saving_outside_for_anyone(self):
        self.assertIn(generate_files.REMAKE, team_model.ADMIN_ACTIONS)
        self.assertNotIn(generate_files.GENERATE, team_model.ADMIN_ACTIONS | team_model.READ_ACTIONS)
        self.assertIn("export_step_pdf", team_model.READ_ACTIONS)


@SKIP_ON_WINDOWS
class GenerateFlow(EngineFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sw = FakeSolidWorks()

    def generate(self, repo, kinds=BOTH, force=False, pns=(PART,)):
        return generate_files.generate(repo, list(pns), kinds, force=force, backend_factory=lambda: self.sw)

    def test_a_release_gets_its_step_and_pdf_uploaded_straight_after(self):
        with self.user("Alex"):
            lifecycle.release(self.a, PART)
            result = generate_files.after_release(self.a, [PART], backend_factory=lambda: self.sw)
            self.assertEqual(result.done, [(PART, [STEP, PDF])])
            self.assertEqual(result.failed, [])
            self.assertIn("HCR-00001-001: STEP/PDF made", self.remote_log())
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse(is_writable(self.a / STEP))
            record = record_store.load(self.a, PART)
            self.assertFalse(record_exports.is_flagged(record))
            self.assertEqual(record.history[-1]["event"], "files_made")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual((self.b / PDF).read_text(), "PDF of HCR-00001-001_A.SLDDRW\n")

    def test_without_solidworks_the_release_stands_and_the_part_stays_flagged(self):
        broken = FakeSolidWorks(broken={"HCR-00001-001_A.SLDPRT", "HCR-00001-001_A.SLDDRW"})
        with self.user("Alex"):
            lifecycle.release(self.a, PART)
            log = self.remote_log()
            result = generate_files.after_release(self.a, [PART], backend_factory=lambda: broken)
            self.assertEqual(result.done, [])
            self.assertIn("could not make", result.failed[0][1])
            self.assertEqual(self.remote_log(), log)                  # nothing uploaded
            record = record_store.load(self.a, PART)
            self.assertEqual(record.status, "released")
            self.assertTrue(record_exports.is_flagged(record))
            self.assertEqual(self.locks(self.a), {})
            self.assertFalse((self.a / STEP).exists())
            # later, with SolidWorks: the flag is what lets anyone make them
            self.assertEqual(self.generate(self.a).done, [(PART, [STEP, PDF])])
            self.assertFalse(record_exports.is_flagged(record_store.load(self.a, PART)))

    def test_after_release_leaves_parts_it_did_not_just_release_alone(self):
        with self.user("Alex"):
            self.assertEqual(generate_files.after_release(self.a, [PART], backend_factory=lambda: self.sw).done, [])
            self.assertEqual(self.sw.saved, [])

    def test_up_to_date_released_files_are_made_again_only_by_force(self):
        with self.user("Alex"):
            lifecycle.release(self.a, PART)
            generate_files.after_release(self.a, [PART], backend_factory=lambda: self.sw)
            result = self.generate(self.a)
            self.assertIn("up to date", result.failed[0][1])
            result = self.generate(self.a, force=True)
            self.assertEqual(result.done, [(PART, [STEP, PDF])])
            self.assertTrue(record_store.load(self.a, PART).history[-1]["forced"])

    def test_your_checkout_keeps_them_until_you_check_in(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            log = self.remote_log()
            result = self.generate(self.a, kinds=[record_exports.STEP])
            self.assertEqual(result.done, [(PART, [STEP])])
            self.assertEqual(self.remote_log(), log)
            self.assertIn("step", record_store.load(self.a, PART).exports["A"])
            self.assertIn(REC.lower(), self.locks(self.a))            # still checked out
            checkin.checkin(self.a, PART, "With its STEP")
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertTrue((self.b / STEP).exists())
            self.assertIn("step", record_store.load(self.b, PART).exports["A"])

    def test_someone_elses_checkout_is_refused(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            result = self.generate(self.b)
            self.assertIn("checked out by", result.failed[0][1])
            self.assertEqual(self.sw.saved, [])

    def test_an_in_work_part_nobody_has_is_done_and_uploaded(self):
        with self.user("Alex"):
            (self.a / "cad/HCR-00001-001_A.STP").write_text("an old STEP")
            git(self.a, "add", ".")
            git(self.a, "commit", "-m", "Old STEP")
            git(self.a, "push")
            result = self.generate(self.a)
            self.assertEqual(result.done, [(PART, ["cad/HCR-00001-001_A.STP", PDF])])   # replaced under its name
            self.assertEqual((self.a / "cad/HCR-00001-001_A.STP").read_text(), "STEP of HCR-00001-001_A.SLDPRT\n")
            self.assertFalse((self.a / STEP).exists())


if __name__ == "__main__":
    unittest.main()
