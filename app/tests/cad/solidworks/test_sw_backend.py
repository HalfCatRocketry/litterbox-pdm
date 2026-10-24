"""Tests for cad/solidworks/sw_backend.py with a pretend SolidWorks (COM itself can only be tried on Windows with SolidWorks)."""

import unittest
from pathlib import Path
from litterbox.cad.solidworks import sw_backend
from litterbox.cad.solidworks import sw_errors
from tests.support import temp_folders


class PairReferences(unittest.TestCase):
    def test_lists_that_line_up_are_paired_by_position(self):
        self.assertEqual(sw_backend.pair_references(["/old/a.SLDPRT", "/old/b.SLDPRT"], ["/x/a.SLDPRT", "/y/b.SLDPRT"]),
                         [("/old/a.SLDPRT", "/x/a.SLDPRT"), ("/old/b.SLDPRT", "/y/b.SLDPRT")])

    def test_lists_that_do_not_line_up_are_paired_by_unique_file_name(self):
        pairs = sw_backend.pair_references(["/old/a.SLDPRT", "/old/c.SLDPRT"], ["/y/a.SLDPRT", "/z/a.SLDPRT", "/y/b.SLDPRT"])
        self.assertEqual(pairs, [("/old/a.SLDPRT", ""), ("/old/c.SLDPRT", "")])
        pairs = sw_backend.pair_references(["/old/a.SLDPRT"], ["/y/a.SLDPRT", "/y/b.SLDPRT"])
        self.assertEqual(pairs, [("/old/a.SLDPRT", "/y/a.SLDPRT")])


class CopyingWhenSolidWorksRefuses(unittest.TestCase):
    """SolidWorks sometimes refuses CopyDocument (it returned 2 for a McMaster washer). A lone part is copied as
    an ordinary file; anything else is reported."""

    def setUp(self):
        import sys
        import tempfile
        import types
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.dir)
        fake_pythoncom = types.ModuleType("pythoncom")
        fake_pythoncom.VT_ARRAY, fake_pythoncom.VT_BSTR = 0x2000, 8
        client = types.ModuleType("win32com.client")
        client.VARIANT = lambda kind, value: value
        win32com = types.ModuleType("win32com")
        win32com.client = client
        for name, module in (("pythoncom", fake_pythoncom), ("win32com", win32com), ("win32com.client", client)):
            old = sys.modules.get(name)
            sys.modules[name] = module
            self.addCleanup(lambda n=name, o=old: sys.modules.pop(n, None) if o is None else sys.modules.update({n: o}))

    def backend(self, deps):
        class App:
            def CopyDocument(inner, *args):
                return 2                                    # refused, and nothing was written

        backend = sw_backend.SolidWorksBackend()
        backend._sw = App()
        backend._dependencies = lambda path, search: deps
        return backend

    def test_a_lone_part_is_copied_as_a_file(self):
        src = self.dir / "washer.SLDPRT"
        src.write_bytes(b"washer")
        dst = self.dir / "vault" / "cad" / "HCR-00002-001_A.SLDPRT"
        self.backend([]).copy(str(src), str(dst))
        self.assertEqual(dst.read_bytes(), b"washer")

    def test_a_file_with_references_is_reported_not_copied_blindly(self):
        src = self.dir / "bracket.SLDASM"
        src.write_bytes(b"asm")
        dst = self.dir / "out" / "x.SLDASM"
        with self.assertRaises(sw_errors.SolidWorksError) as ctx:
            self.backend([]).copy(str(src), str(dst))
        self.assertIn("it returned 2", str(ctx.exception))
        self.assertFalse(dst.exists())
        part = self.dir / "uses.SLDPRT"
        part.write_bytes(b"p")
        with self.assertRaises(sw_errors.SolidWorksError):
            self.backend(["C:/other.SLDPRT"]).copy(str(part), str(self.dir / "out" / "y.SLDPRT"))


class ComponentsAndToolbox(unittest.TestCase):
    """An assembly's components and which are Toolbox parts are read with one opening, and kept while the file is
    unchanged. (ToolboxPartType tried with SolidWorks 2024: a Toolbox screw 1, an ordinary part 0.)"""

    def setUp(self):
        import contextlib
        import tempfile
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(temp_folders.remove, self.dir)
        self.asm = self.dir / "HCR-00002-500_A.SLDASM"
        self.asm.write_bytes(b"asm")
        self.opened = 0

        class Component:
            def __init__(inner, path, kind, suppressed=False):
                inner.path, inner.kind, inner.suppressed = path, kind, suppressed

            def GetPathName(inner):
                return inner.path

            def IsSuppressed(inner):
                return inner.suppressed

            def ExcludeFromBOM(inner):
                return False

            def IsEnvelope(inner):
                return False

            def GetModelDoc2(inner):
                if inner.suppressed:
                    return None
                return type("Doc", (), {"Extension": type("Ext", (), {"ToolboxPartType": inner.kind})()})()

        class Model:
            def GetComponents(inner, top_only):
                return [Component("C:/v/cad/HCR-00001-001_A.SLDPRT", 0),
                        Component("C:/SOLIDWORKS Data/browser/screw.sldprt", 1),
                        Component("C:/v/cad/HCR-00003-001_A.SLDPRT", 2),
                        Component("C:/SOLIDWORKS Data/browser/nut.sldprt", 1, suppressed=True)]

        @contextlib.contextmanager
        def opened(path, doc_type):
            self.opened += 1
            yield Model()

        self.backend = sw_backend.SolidWorksBackend()
        self.backend._opened = opened

    def test_one_opening_gives_both_and_a_copied_toolbox_part_is_a_part(self):
        self.assertEqual(self.backend.library_components(str(self.asm)), ["C:/SOLIDWORKS Data/browser/screw.sldprt"])
        self.assertEqual([state for _file, state in self.backend.components(str(self.asm))],
                         ["counted", "counted", "counted", "suppressed"])
        self.assertEqual(self.opened, 1)

    def test_a_changed_file_is_read_again(self):
        import os
        self.backend.components(str(self.asm))
        os.utime(self.asm, ns=(1, 1))
        self.backend.library_components(str(self.asm))
        self.assertEqual(self.opened, 2)


if __name__ == "__main__":
    unittest.main()
