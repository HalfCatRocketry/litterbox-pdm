"""Tests for cad/cad_programs.py and cad/cad_program.py: the program for a file, the backend that hands each call to
its file's program, and the base CadProgram that can do nothing; and core/file_types.py, which they choose by."""

import contextlib
import unittest

from litterbox.cad import cad_program
from litterbox.cad import cad_programs
from litterbox.cad.cad_errors import CadError
from litterbox.cad.solidworks import sw_errors
from litterbox.cad.solidworks import sw_program
from litterbox.core import file_types
from litterbox.importing import scan
from tests.support.gui_fakes import replace


class FakeBackend:
    def __init__(self, name, log):
        self.name, self.log = name, log

    def __getattr__(self, call):
        def record(*args):
            self.log.append((self.name, call, args))
            return f"{self.name}:{call}"
        return record


class FakeProgram(cad_program.CadProgram):
    def __init__(self, name, log, running=True):
        self.name, self.log, self.running = name, log, running

    def backend(self, attach_only=False):
        self.log.append((self.name, "made", attach_only))
        return FakeBackend(self.name, self.log)

    @contextlib.contextmanager
    def session(self):
        self.log.append((self.name, "session"))
        yield

    def open_read_only(self, paths):
        return [f"{self.name}:{p}" for p in paths] if self.running else None


class FileTypes(unittest.TestCase):
    def test_solidworks_files_are_known_by_kind_and_program(self):
        self.assertEqual(file_types.kind_of("cad/HCR-00001-001_A.SLDASM"), file_types.ASSEMBLY)
        self.assertEqual(file_types.kind_of("x.sldprt"), file_types.PART)
        self.assertEqual(file_types.kind_of("x.SLDDRW"), file_types.DRAWING)
        self.assertIsNone(file_types.kind_of("x.STEP"))
        self.assertEqual(file_types.program_of("C:\\a\\x.SldPrt"), "SolidWorks")
        self.assertIsNone(file_types.program_of("notes.txt"))
        self.assertTrue(file_types.is_cad("a.slddrw") and file_types.is_model("a.sldasm") and not file_types.is_cad("a.pdf"))

    def test_the_lists_are_every_programs_together(self):
        self.assertEqual(file_types.CAD_EXTENSIONS, (".sldprt", ".sldasm", ".slddrw"))
        self.assertEqual(file_types.MODEL_EXTENSIONS, (".sldprt", ".sldasm"))

    def test_the_importer_scans_every_programs_files(self):
        self.assertEqual(scan.FORMATS[".sldasm"], ("assembly", "SLDASM"))
        self.assertEqual(scan.FORMATS[".step"], ("export", "STEP"))


class ChoosingAProgram(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.cam = FakeProgram("SolidWorks", self.log)
        self.ecad = FakeProgram("KiCad", self.log, running=False)
        replace(self, cad_programs, "PROGRAMS", (self.cam, self.ecad))
        replace(self, cad_programs, "DEFAULT", self.cam)
        replace(self, file_types, "PROGRAMS", {"SolidWorks": {file_types.PART: (".sldprt",)},
                                              "KiCad": {file_types.PART: (".kicad_pcb",)}})

    def test_by_extension(self):
        self.assertIs(cad_programs.for_file("cad/HCR-00001-001_A.SLDPRT"), self.cam)
        self.assertIs(cad_programs.for_file("board.kicad_pcb"), self.ecad)
        self.assertIsNone(cad_programs.for_file("notes.txt"))
        self.assertEqual(cad_programs.for_files(["b.kicad_pcb", "a.sldprt", "c.kicad_pcb", "x.pdf"]),
                         [self.ecad, self.cam])

    def test_each_call_goes_to_its_files_program_and_each_backend_is_made_once(self):
        backends = cad_programs.Backends(attach_only=True)
        self.assertEqual(backends.references("a.sldprt"), "SolidWorks:references")
        self.assertEqual(backends.copy("b.kicad_pcb", "c.kicad_pcb"), "KiCad:copy")
        backends.material("d.sldprt")
        made = [entry for entry in self.log if entry[1] == "made"]
        self.assertEqual(made, [("SolidWorks", "made", True), ("KiCad", "made", True)])
        self.assertEqual(backends.version(), "SolidWorks:version")          # no file: the default program
        backends.close()
        self.assertIn(("KiCad", "close", ()), self.log)

    def test_a_file_no_program_knows_is_refused(self):
        with self.assertRaisesRegex(CadError, "notes.txt"):
            cad_programs.Backends().references("C:/x/notes.txt")

    def test_a_session_is_every_programs(self):
        with cad_programs.session():
            pass
        self.assertEqual(self.log, [("SolidWorks", "session"), ("KiCad", "session")])

    def test_open_documents_are_asked_of_each_program_and_none_means_none_running(self):
        self.assertEqual(cad_programs.open_read_only(["a.sldprt", "b.kicad_pcb"]), ["SolidWorks:a.sldprt"])
        replace(self, self.cam, "running", False)
        self.assertIsNone(cad_programs.open_read_only(["a.sldprt"]))
        done, failed = cad_programs.make_writable(["b.kicad_pcb"])
        self.assertEqual((done, [path for path, _why in failed]), ([], ["b.kicad_pcb"]))

    def test_closing_closes_every_backend_even_if_one_fails(self):
        backends = cad_programs.Backends()
        backends.references("a.sldprt")
        backends.references("b.kicad_pcb")
        closed = []

        class Broken:
            def close(self):
                raise RuntimeError("stuck")
        backends._made["SolidWorks"] = Broken()
        backends._made["KiCad"].close = lambda: closed.append("KiCad")
        with self.assertRaisesRegex(RuntimeError, "stuck"):
            backends.close()
        self.assertEqual(closed, ["KiCad"])


class TheRealPrograms(unittest.TestCase):
    def test_solidworks_is_the_one_program_and_its_errors_are_cad_errors(self):
        self.assertEqual([p.name for p in cad_programs.PROGRAMS], ["SolidWorks"])
        self.assertIs(cad_programs.DEFAULT, sw_program.SOLIDWORKS)
        self.assertEqual(sw_program.SOLIDWORKS.library_name, "Toolbox")
        self.assertEqual(sw_program.SOLIDWORKS.extensions, file_types.CAD_EXTENSIONS)
        self.assertTrue(issubclass(sw_errors.SolidWorksError, CadError))

    def test_a_program_that_can_do_nothing_says_so(self):
        nothing = cad_program.CadProgram()
        self.assertFalse(nothing.installed())
        self.assertIsNone(nothing.watcher(lambda changes: None))
        self.assertIsNone(nothing.open_read_only(["a"]))
        self.assertEqual(nothing.library_folder(), "")
        with self.assertRaises(CadError):
            nothing.backend()


if __name__ == "__main__":
    unittest.main()
