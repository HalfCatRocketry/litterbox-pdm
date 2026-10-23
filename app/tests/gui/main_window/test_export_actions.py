"""Tests for the wiring of Export Files, Export BOM and Purchasing Info in the main window. The window itself is
replaced by stand-ins (tests/support/gui_fakes.py): these check the wiring, not the look."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from litterbox.core.part_number import PN
from litterbox.parts.part_status import PartStatus
from tests.support.gui_fakes import FakeBox, load_gui_with_fakes, replace
from tests.support import temp_folders

PART = PN("HCR", 7, 1)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.box = FakeBox()
        self.gui = load_gui_with_fakes(self.box)
        self.row = PartStatus(PART, "Bracket", "released", "Released", "released",
                              revisions={"A": ["cad/HCR-00007-001_A.SLDPRT"]})
        app = self.gui.app.App.__new__(self.gui.app.App)
        app.rows_by_pn = {PART: self.row}
        app.repo = lambda: "C:/vault"
        app.settings = {}
        app._plan = lambda action: SimpleNamespace(targets=[PART])
        self.said, self.tasks = [], []
        app._say = lambda text, tone="normal": self.said.append(text)
        app.run_task = lambda work, done, on_success=None, **kw: self.tasks.append((work, on_success, kw))
        self.app = app
        replace(self, self.gui.settings, "save", lambda data, path=None: None)
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.out)

    def answer_dialog(self, module, cls, answer):
        asked = []

        class Fake:
            def __init__(self, *args, **kwargs):
                asked.append(args)

            def show(self):
                return answer
        replace(self, module, cls, Fake)
        return asked

    def test_export_files_plans_then_copies_in_the_background_and_remembers_the_folder(self):
        self.answer_dialog(self.gui.export_files_dialog, "ExportFilesDialog",
                           {"kinds": ["model"], "which": "released", "with_used": False, "folder": self.out})
        plan = self.gui.part_files_export.ExportPlan(files=["cad/HCR-00007-001_A.SLDPRT"], notes=[])
        replace(self, self.gui.part_files_export, "plan", lambda *a, **k: plan)
        copied = []
        replace(self, self.gui.part_files_export, "export",
                lambda repo, files, folder, root, replace=False: copied.append((files, folder, replace)) or ["x"])
        self.app.export_files()
        self.assertEqual(len(self.tasks), 1)
        work, on_success, kw = self.tasks[0]
        self.assertEqual(kw["refresh"], False)
        on_success(work())
        self.assertEqual(copied, [(plan.files, self.out, True)])
        self.assertEqual(self.app.settings["export_folder"], str(self.out))
        self.assertEqual(self.said[-1], f"Exported 1 file to {self.out}.")

    def test_export_files_asks_before_replacing_and_stops_on_no(self):
        self.answer_dialog(self.gui.export_files_dialog, "ExportFilesDialog",
                           {"kinds": ["model"], "which": "released", "with_used": False, "folder": self.out})
        (self.out / "HCR-00007-001_A.SLDPRT").write_text("old")
        replace(self, self.gui.part_files_export, "plan",
                lambda *a, **k: self.gui.part_files_export.ExportPlan(files=["cad/HCR-00007-001_A.SLDPRT"]))
        self.box.answer = False
        self.app.export_files()
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.box.calls[-1][0], "askyesno")

    def test_cancelling_export_files_does_nothing(self):
        self.answer_dialog(self.gui.export_files_dialog, "ExportFilesDialog", None)
        self.app.export_files()
        self.assertEqual(self.tasks, [])

    def test_export_bom_refuses_a_file_inside_litterbox(self):
        self.app.pane_pn = PART
        replace(self, self.gui.filedialog, "asksaveasfilename", lambda **k: str(self.gui.settings.ROOT / "bom.csv"))
        self.app.export_bom("A", "indented")
        self.assertEqual(self.tasks, [])
        self.assertEqual(self.box.calls[-1][0], "showwarning")

    def test_export_bom_writes_in_the_background(self):
        self.app.pane_pn = PART
        offered = {}

        def save_as(**options):
            offered.update(options)
            return str(self.out / "bom.csv")
        replace(self, self.gui.filedialog, "asksaveasfilename", save_as)
        self.app.export_bom("A", "flat")
        self.assertEqual(offered["initialfile"], "HCR-00007-001_A BOM (every part once).csv")
        self.assertEqual(len(self.tasks), 1)

    def test_purchasing_info_sends_what_was_typed(self):
        record = SimpleNamespace(purchasing={"supplier": "Acme"})
        replace(self, self.gui.record_store, "load", lambda repo, pn: record)
        asked = self.answer_dialog(self.gui.purchasing_dialog, "PurchasingDialog", {"supplier": "Bolt Co"})
        sent = []
        replace(self, self.gui.purchasing, "edit_purchasing", lambda repo, pn, fields: sent.append(fields) or "uploaded")
        self.app.edit_purchasing()
        self.assertEqual(asked[0][1:3], (PART, {"supplier": "Acme"}))
        self.assertIn("uploaded as soon as you save", asked[0][3])
        work, on_success, _kw = self.tasks[0]
        on_success(work())
        self.assertEqual(sent, [{"supplier": "Bolt Co"}])
        self.assertEqual(self.said[-1], "Updated the purchasing info of HCR-00007-001.")


if __name__ == "__main__":
    unittest.main()
