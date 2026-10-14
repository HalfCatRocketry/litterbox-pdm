"""Tests for recording an assembly's references at check-in (reference_reader). They need Linux, macOS or WSL."""

import unittest
from tests.support.vault_fixture import PART, PRT, REC, git
from litterbox.references import reference_reader
from litterbox.parts import revise
from litterbox.parts import checkin
from litterbox.parts import checkout
from litterbox.parts import get_latest
from litterbox.parts import lifecycle
from tests.support.references_fixture import ASM, ASM_FILE, STEM_A, RefsFixture


class TestRecordingReferences(RefsFixture, unittest.TestCase):
    def test_checkin_stores_what_the_assembly_uses(self):
        record = self.record()
        self.assertEqual(record.references, {"A": [STEM_A]})
        event = [e for e in record.history if e["event"] == "checked_in"][-1]
        self.assertEqual(event["references"], [STEM_A])
        text = (self.a / REC.replace("00001", "00002")).read_text()
        self.assertIn("references:", text)

    def test_other_users_see_them_after_get_latest(self):
        with self.user("Bea"):
            get_latest.get_latest(self.b)
            self.assertEqual(self.record(self.b).references, {"A": [STEM_A]})

    def test_a_part_with_no_assembly_file_has_no_references(self):
        self.assertEqual(self.record(pn=PART).references, {})

    def test_unreadable_solidworks_does_not_block_the_checkin(self):
        class Broken:
            def references(self, path):
                raise RuntimeError("SolidWorks is not available")

            def close(self):
                pass

        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text("assembly A, edited\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=reference_reader.make_reader(Broken(), self.log.append))
        self.assertEqual(self.record().references, {"A": [STEM_A]})            # unchanged
        self.assertTrue(any("could not read" in line for line in self.log))
        self.assertEqual(git(self.a, "rev-list", "--count", "@{u}..HEAD"), "0")

    def test_check_in_never_starts_solidworks(self):
        from unittest import mock
        made = []

        def fake_new_backend(attach_only=False):
            made.append(attach_only)
            raise RuntimeError("SolidWorks is not open.")

        with self.user("Alex"), mock.patch.object(reference_reader, "new_backend", fake_new_backend):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text("assembly A, edited\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Edit", references_reader=reference_reader.make_reader(log=self.log.append))
        self.assertEqual(made, [True])                                 # asked to attach only
        self.assertEqual(self.record().references, {"A": [STEM_A]})
        self.assertTrue(any("SolidWorks is not open" in line for line in self.log))

    def test_files_that_are_not_litterbox_files_are_ignored(self):
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            (self.a / ASM_FILE).write_text(f"assembly\nref: {self.a / PRT}\nref: /lib/screw.SLDPRT\n", encoding="utf-8")
            checkin.checkin(self.a, ASM, "Add a screw", references_reader=reference_reader.make_reader(self.fake))
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_the_reader_does_not_touch_solidworks_when_no_assembly_changed(self):
        class Spy:
            calls = 0

            def references(self, path):
                Spy.calls += 1
                return []

        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            checkin.checkin(self.a, ASM, "No file change", allow_unchanged=True,
                        references_reader=reference_reader.make_reader(Spy()))
        self.assertEqual(Spy.calls, 0)
        self.assertEqual(self.record().references, {"A": [STEM_A]})

    def test_revise_copies_references_to_the_new_revision(self):
        with self.user("Alex"):
            checkout.checkout(self.a, ASM)
            checkin.checkin(self.a, ASM, "x", allow_unchanged=True)
            lifecycle.release(self.a, ASM)
            revise.revise(self.a, ASM, "Rework", backend=self.fake, log=lambda *_: None)
        self.assertEqual(self.record().references, {"A": [STEM_A], "B": [STEM_A]})


if __name__ == "__main__":
    unittest.main()
