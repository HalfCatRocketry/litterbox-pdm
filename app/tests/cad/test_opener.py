import tempfile
import unittest
from pathlib import Path


from litterbox.cad import opener
from litterbox.parts.engine import LitterboxError


class OpenOrder(unittest.TestCase):
    def test_model_first_then_drawing_then_the_rest(self):
        files = ["cad/A.SLDDRW", "cad/A.pdf", "cad/A.SLDPRT"]
        self.assertEqual(opener.open_order(files), ["cad/A.SLDPRT", "cad/A.SLDDRW", "cad/A.pdf"])

    def test_assembly_counts_as_a_model(self):
        self.assertEqual(opener.open_order(["cad/A.SLDDRW", "cad/A.SLDASM"])[0], "cad/A.SLDASM")


class PickFiles(unittest.TestCase):
    def test_model_and_drawing(self):
        files = ["cad/A.SLDDRW", "cad/A.SLDPRT"]
        self.assertEqual(opener.pick_model(files), "cad/A.SLDPRT")
        self.assertEqual(opener.pick_drawing(files), "cad/A.SLDDRW")

    def test_no_drawing_or_no_model(self):
        self.assertIsNone(opener.pick_drawing(["cad/A.SLDPRT"]))
        self.assertEqual(opener.pick_model(["cad/A.SLDDRW"]), "cad/A.SLDDRW")      # falls back to what there is
        self.assertIsNone(opener.pick_model([]))


class ProgramFor(unittest.TestCase):
    def test_settings_choose_a_program_by_extension(self):
        chosen = {".pdf": "C:/Acrobat.exe", "PNG": "C:/view.exe"}
        self.assertEqual(opener.program_for("cad/x.PDF", chosen), "C:/Acrobat.exe")
        self.assertEqual(opener.program_for("C:\\v\\x.png", chosen), "C:/view.exe")
        self.assertIsNone(opener.program_for("cad/x.SLDPRT", chosen))
        self.assertIsNone(opener.program_for("cad/x.pdf", None))
        self.assertIsNone(opener.program_for("cad/x.pdf", {".pdf": ""}))


class OpenPath(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.file = self.dir / "part.SLDPRT"
        self.file.write_text("x")
        self.pdf = self.dir / "doc.pdf"
        self.pdf.write_text("x")

    def test_default_uses_the_windows_association(self):
        started = []
        opener.open_path(self.file, {}, startfile=started.append)
        self.assertEqual(started, [str(self.file)])

    def test_a_hidden_solidworks_is_shown_before_a_solidworks_file_opens(self):
        order = []
        opener.open_path(self.file, {}, startfile=lambda p: order.append("open"),
                         show_hidden=lambda: order.append("show"))
        self.assertEqual(order, ["show", "open"])

    def test_other_files_do_not_touch_solidworks(self):
        order = []
        opener.open_path(self.pdf, {}, startfile=lambda p: order.append("open"),
                         show_hidden=lambda: order.append("show"))
        self.assertEqual(order, ["open"])

    def test_a_chosen_program_is_used_for_that_type_only(self):
        program = self.dir / "viewer.exe"
        program.write_text("x")
        launched, started = [], []
        settings = {".pdf": str(program)}
        opener.open_path(self.pdf, settings, startfile=started.append, popen=launched.append)
        opener.open_path(self.file, settings, startfile=started.append, popen=launched.append)
        self.assertEqual(launched, [[str(program), str(self.pdf)]])
        self.assertEqual(started, [str(self.file)])

    def test_missing_file_or_program_gives_a_plain_message(self):
        with self.assertRaises(LitterboxError) as ctx:
            opener.open_path(self.dir / "gone.SLDPRT", {}, startfile=lambda p: None)
        self.assertIn("Get Latest", str(ctx.exception))
        with self.assertRaises(LitterboxError) as ctx:
            opener.open_path(self.pdf, {".pdf": str(self.dir / "nope.exe")}, popen=lambda a: None)
        self.assertIn("settings.yaml", str(ctx.exception))

    def test_os_errors_become_litterbox_errors(self):
        def broken(path):
            raise OSError("no association")
        with self.assertRaises(LitterboxError) as ctx:
            opener.open_path(self.file, {}, startfile=broken)
        self.assertIn("no association", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()