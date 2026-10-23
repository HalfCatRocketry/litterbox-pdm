"""Tests for the wiring of Generate STEP/PDF and the files made after a release, in the main window. The window
itself is replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.errors import LitterboxError
from litterbox.parts.part_status import PartStatus
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace
from tests.support import temp_folders

PART = PN("HCR", 7, 1)
FILES = ["cad/HCR-00007-001_A.SLDDRW", "cad/HCR-00007-001_A.SLDPRT"]


class Harness(unittest.TestCase):
    """The main window with stand-ins, one ticked part, and a way to answer the Generate STEP/PDF window."""

    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.row = PartStatus(PART, "Bracket", "in_work", "Available", "ok", files=FILES, revisions={"A": FILES})
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {PART: self.row}
        app.repo = lambda: "C:/vault"
        app.settings, app.note = {}, ""
        app.jobs = SimpleNamespace(pending_parts=lambda: {})
        app._selected_pns = lambda action: [PART]
        self.denied = set()
        app.identity = SimpleNamespace(allows=lambda action: (action not in self.denied, "Only an Admin can do that."))
        self.said, self.tasks, self.logged = [], [], []
        app._say = lambda text, tone="normal": self.said.append((text, tone))
        app._log = self.logged.append
        app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, on_success, kw))
        self.app = app
        replace(self, self.gui.settings, "save", lambda data, path=None: None)
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.out)

    def answer_dialog(self, answer):
        asked = []

        class Fake:
            def __init__(self, *args, **kwargs):
                asked.append((args, kwargs))

            def show(self):
                return answer
        replace(self, self.gui.generate_files_dialog, "GenerateFilesDialog", Fake)
        return asked


class Wiring(Harness):
    def test_in_the_vault_it_generates_in_the_background_and_reports(self):
        asked = self.answer_dialog({"kinds": ["step", "pdf"], "where": "vault", "folder": None, "force": False,
                                    "pns": [PART]})
        seen = []
        result = self.gui.generate_files.Generated(done=[(PART, ["cad/HCR-00007-001_A.STEP"])])
        replace(self, self.gui.generate_files, "generate",
                lambda repo, pns, kinds, force=False: seen.append((pns, kinds, force)) or result)
        self.app.generate_step_pdf()
        self.assertEqual(asked[0][0][2], [self.row])                   # the table's parts
        self.assertEqual(asked[0][1], {"may_vault": True, "is_admin": True})
        work, on_success, kw = self.tasks[0]
        self.assertEqual(kw["parts"], [PART])
        on_success(work())
        self.assertEqual(seen, [([PART], ["step", "pdf"], False)])
        self.assertEqual(self.app.note, "Made 1 file for 1 part")

    def test_a_failure_is_shown(self):
        self.answer_dialog({"kinds": ["step"], "where": "vault", "folder": None, "force": True, "pns": [PART]})
        self.app.generate_step_pdf()
        _work, on_success, _kw = self.tasks[0]
        on_success(self.gui.generate_files.Generated(failed=[(PART, "SolidWorks is not installed")]))
        self.assertEqual(self.box.calls[-1][0], "showerror")
        self.assertIn("not installed", self.box.calls[-1][1][1])

    def test_without_write_access_only_a_folder_outside_is_offered(self):
        self.denied = {"generate_files", "remake_files"}
        asked = self.answer_dialog(None)
        self.app.generate_step_pdf()
        self.assertEqual(asked[0][1], {"may_vault": False, "is_admin": False})
        self.assertEqual(self.tasks, [])

    def test_outside_it_asks_before_replacing_then_saves_to_the_folder(self):
        self.answer_dialog({"kinds": ["step", "pdf"], "where": "outside", "folder": self.out, "force": False,
                            "pns": [PART]})
        (self.out / "HCR-00007-001_A.PDF").write_text("old")
        self.box.answer = False
        self.app.generate_step_pdf()
        self.assertEqual((self.box.calls[-1][0], self.tasks), ("askyesno", []))
        self.box.answer = True
        made = []
        replace(self, self.gui.step_pdf, "make", lambda repo, jobs, folder: made.append(folder) or
                self.gui.step_pdf.Made(made={PART: {"step": {}, "pdf": {}}}))
        replace(self, self.gui.step_pdf, "jobs_for", lambda repo, pns, kinds: (["job"], []))
        self.app.generate_step_pdf()
        work, on_success, kw = self.tasks[0]
        self.assertFalse(kw["refresh"])
        on_success(work())
        self.assertEqual(made, [self.out])
        self.assertEqual(self.said[-1], (f"Saved 2 files to {self.out}", "normal"))
        self.assertEqual(self.app.settings["export_folder"], str(self.out))


class AfterRelease(Harness):
    def test_the_files_are_made_in_the_same_job_and_reported(self):
        made_for = []
        files = self.gui.generate_files.Generated(done=[(PART, ["a", "b"])])
        replace(self, self.gui.generate_files, "after_release", lambda repo, pns: made_for.append(pns) or files)
        got = []
        self.app.note = "Released 1 part"
        self.app.run_releasing(lambda: "released", [PART], "", on_success=got.append, label="Releasing")
        work, on_success, kw = self.tasks[0]
        self.assertEqual(kw["label"], "Releasing")
        on_success(work())
        self.assertEqual((got, made_for), (["released"], [[PART]]))
        self.assertEqual(self.app.note, "Released 1 part. Made 2 files for 1 part")

    def test_without_solidworks_the_part_is_flagged_and_the_line_says_so(self):
        failed = self.gui.generate_files.Generated(failed=[(PART, "SolidWorks is not installed on this computer")])
        replace(self, self.gui.generate_files, "after_release", lambda repo, pns: failed)
        self.app.run_releasing(lambda: "released", [PART], "")
        work, on_success, _kw = self.tasks[0]
        on_success(work())
        text, tone = self.said[-1]
        self.assertEqual(tone, "warn")
        self.assertIn("flagged", text)
        self.assertIn("not installed", text)

    def test_a_failed_release_still_makes_files_for_what_it_did(self):
        made_for = []
        replace(self, self.gui.generate_files, "after_release", lambda repo, pns: made_for.append(pns))

        def work():
            raise LitterboxError("Done on HCR-00007-001. HCR-00008-001: offline")
        self.app.run_releasing(work, [PART], "")
        with self.assertRaises(LitterboxError):
            self.tasks[0][0]()
        self.assertEqual(made_for, [[PART]])


if __name__ == "__main__":
    unittest.main()
