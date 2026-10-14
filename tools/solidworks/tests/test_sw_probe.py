"""Tests for sw_probe.py using a pretend SolidWorks. (The real connection can only be tried on Windows with
SolidWorks installed.) Run from tools/solidworks with the app folder on PYTHONPATH:  python -m unittest discover -s tests -v"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import sw_probe


class FakeComponent:
    def __init__(self, name, path, suppressed=False, configuration="Default"):
        self.Name2 = name                                   # a property
        self.ReferencedConfiguration = configuration       # a property
        self._path, self._suppressed = path, suppressed

    def GetPathName(self):                                  # methods
        return self._path

    def IsSuppressed(self):
        return self._suppressed


class FakeModel:
    def __init__(self, components):
        self._components = components

    def GetComponents(self, top_level_only):
        return tuple(self._components)

    def GetTitle(self):
        return "Assembly.SLDASM"


class FakeSW:
    def __init__(self, model=None, drop=(), on_close=None):
        self._model, self._drop, self._on_close = model, set(drop), on_close
        self.Visible = False
        self.closed, self.saved = [], []

    def __getattr__(self, name):
        if name in self._drop or name.startswith("_"):
            raise AttributeError(name)
        if name == "RevisionNumber":
            return lambda: "32.1.0"
        if name == "GetDocumentDependencies2":
            return lambda *args: ("Part.SLDPRT", r"C:\vault\Part.SLDPRT")
        if name == "CloseDoc":
            def close(title):
                self.closed.append(title)
                if self._on_close:
                    self._on_close()
            return close
        if name in ("Save", "Save3", "SaveAs", "SaveAs3", "ExitApp"):
            raise AssertionError(f"the probe must never call {name}")
        return lambda *args: None


class ProbeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.assembly = self.folder / "Assembly.SLDASM"
        self.assembly.write_bytes(b"assembly")
        (self.folder / "Part.SLDPRT").write_bytes(b"part")
        (self.folder / "notes.txt").write_text("hello")

    def run_probe(self, sw, opener=None):
        lines = []
        opener = opener or (lambda s, path: (sw._model, 0, 0))
        sw_probe.probe(str(self.assembly), sw, open_func=opener, log=lines.append)
        return "\n".join(lines)


class TestProbe(ProbeTestCase):
    def test_lists_components_and_reports_an_untouched_folder(self):
        outside = r"D:\somewhere else\Bolt.SLDPRT"
        model = FakeModel([FakeComponent("Part-1", str(self.folder / "Part.SLDPRT")),
                           FakeComponent("Bolt-1", outside, suppressed=True, configuration="M6")])
        sw = FakeSW(model)
        text = self.run_probe(sw)
        self.assertIn("SolidWorks version: 32.1.0  (that is SolidWorks 2024)", text)
        self.assertIn("Components (all levels): 2", text)
        self.assertIn("Part-1", text)
        self.assertIn("in the same folder; file exists", text)
        self.assertIn("OUTSIDE the assembly folder; FILE NOT FOUND; suppressed=True; configuration=M6", text)
        self.assertIn("1 component(s) live outside", text)
        self.assertIn("CHECK PASSED", text)
        self.assertEqual(sw.closed, ["Assembly.SLDASM"])            # closed, and the fake raises on any save
        self.assertTrue(sw.Visible)

    def test_missing_api_members_are_reported(self):
        text = self.run_probe(FakeSW(FakeModel([]), drop=("ReplaceReferencedDocument", "MoveDocument")))
        self.assertIn("NO   ReplaceReferencedDocument", text)
        self.assertIn("NO   MoveDocument", text)
        self.assertIn("yes  OpenDoc6", text)

    def test_a_leftover_file_or_a_changed_file_fails_the_check(self):
        lock = self.folder / "~$Assembly.SLDASM"
        sw = FakeSW(FakeModel([]), on_close=lambda: (lock.write_text("lock"),
                                                      (self.folder / "Part.SLDPRT").write_bytes(b"changed")))
        text = self.run_probe(sw)
        self.assertIn("CHECK FAILED", text)
        self.assertIn("added: ~$Assembly.SLDASM", text)
        self.assertIn("modified: Part.SLDPRT", text)

    def test_an_assembly_that_will_not_open_is_reported_not_a_crash(self):
        text = self.run_probe(FakeSW(), opener=lambda s, path: (None, 2, 0))
        self.assertIn("Opened read-only: NO  (error code 2", text)
        self.assertIn("CHECK PASSED", text)

    def test_an_exception_while_opening_still_ends_with_the_folder_check(self):
        def boom(sw, path):
            raise RuntimeError("COM error")
        text = self.run_probe(FakeSW(), opener=boom)
        self.assertIn("Opening the assembly failed", text)
        self.assertIn("CHECK PASSED", text)

    def test_one_unreadable_field_does_not_stop_the_listing(self):
        class Odd(FakeComponent):
            def IsSuppressed(self):
                raise RuntimeError("no luck")
        text = self.run_probe(FakeSW(FakeModel([Odd("Odd-1", str(self.folder / "Part.SLDPRT"))])))
        self.assertIn("could not read", text)
        self.assertIn("Odd-1", text)

    def test_started_by_us_is_noted(self):
        lines = []
        sw_probe.probe(str(self.assembly), FakeSW(FakeModel([])), started_by_us=True,
                       open_func=lambda s, p: (FakeSW()._model, 0, 0), log=lines.append)
        self.assertIn("started by this script", "\n".join(lines))


class TestHelpers(ProbeTestCase):
    def test_call_handles_properties_and_methods(self):
        comp = FakeComponent("A", "p")
        self.assertEqual(sw_probe.call(comp, "Name2"), "A")
        self.assertEqual(sw_probe.call(comp, "GetPathName"), "p")

    def test_snapshot_and_compare(self):
        before = sw_probe.snapshot(self.folder)
        self.assertEqual(sorted(before), ["Assembly.SLDASM", "Part.SLDPRT", "notes.txt"])
        self.assertEqual(len(before["Part.SLDPRT"][2]), 64)             # CAD files are hashed
        self.assertEqual(before["notes.txt"][2], "")
        self.assertEqual(sw_probe.compare(before, sw_probe.snapshot(self.folder)), ([], [], []))
        (self.folder / "new.txt").write_text("x")
        (self.folder / "notes.txt").unlink()
        (self.folder / "Assembly.SLDASM").write_bytes(b"different")
        self.assertEqual(sw_probe.compare(before, sw_probe.snapshot(self.folder)),
                         (["new.txt"], ["notes.txt"], ["Assembly.SLDASM"]))

    def test_command_line_checks_its_input(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(sw_probe.main([str(self.folder / "missing.SLDASM")]), 1)
            self.assertEqual(sw_probe.main([str(self.folder / "Part.SLDPRT")]), 1)
        self.assertIn("is not an existing .SLDASM file", out.getvalue())


if __name__ == "__main__":
    unittest.main()
