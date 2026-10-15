"""Tests for Undo Checkout and the parts list status (parts/undoing.py, part_status.py). They run the real code against real git repos (a bare remote plus a clone each for Alex and Bea) with a fake git-lfs, so they need Linux, macOS or WSL and are skipped on Windows."""

import unittest
from tests.support.vault_fixture import DRW, PART, PRT, SKIP_ON_WINDOWS, git, is_writable
from litterbox.records import record_store
from litterbox.parts import checkout
from litterbox.parts import undoing
from tests.support.engine_fixture import EngineFixture


@SKIP_ON_WINDOWS
class UndoAndStatus(EngineFixture, unittest.TestCase):
    def test_undo_restores_files_and_forgets_the_checkout(self):
        with self.user("Alex"):
            checkout.checkout(self.a, PART)
            (self.a / PRT).write_bytes(b"scribbles")
            (self.a / "cad/HCR-00001-001_A.STEP").write_bytes(b"never uploaded")
            left = undoing.undo_checkout(self.a, PART)
            self.assertEqual(left, ["cad/HCR-00001-001_A.STEP"])
            self.assertEqual((self.a / PRT).read_bytes(), b"version 1")
            self.assertTrue((self.a / "cad/HCR-00001-001_A.STEP").exists())   # not deleted
            self.assertEqual(self.locks(self.a), {})
            self.assertEqual(record_store.load(self.a, PART).history[-1]["event"], "created")
            self.assertFalse(is_writable(self.a / PRT))

    def test_new_part_with_unclaimed_file_can_be_checked_out(self):
        from litterbox.parts import create
        with self.user("Bea"):
            pn = create.new_part(self.b, "Fresh")
            checkout.checkout(self.b, pn)                   # what the New Part button now does
            self.assertEqual(self.status_of(self.b, pn).kind, "mine")
            undoing.undo_checkout(self.b, pn)
            new_file = self.b / "cad" / f"{pn}_A.SLDPRT"
            new_file.write_bytes(b"saved before checkout")
            self.assertEqual(self.status_of(self.b, pn).kind, "unclaimed")
            result = checkout.checkout(self.b, pn)          # claims the file that is already there
            self.assertEqual(result.files, [f"cad/{pn}_A.SLDPRT"])
            self.assertEqual(self.status_of(self.b, pn).kind, "mine")

    def test_status_kinds(self):
        with self.user("Bea"):
            self.assertEqual(self.status_of(self.b).kind, "ok")
            (self.b / PRT).chmod(0o644)
            (self.b / PRT).write_bytes(b"edited without checkout")
            self.assertEqual(self.status_of(self.b).kind, "unclaimed")
            git(self.b, "restore", "--", PRT)
            (self.b / DRW).chmod(0o644)
            (self.b / DRW).write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 9\n")
            self.assertEqual(self.status_of(self.b).kind, "missing")


if __name__ == "__main__":
    unittest.main()
