"""Tests for counting an assembly's parts (reference_reader.read_assembly_quantities and the check-in reader), with a
pretend SolidWorks and no git."""

import shutil
import tempfile
import unittest
from pathlib import Path

from litterbox.cad.solidworks import sw_backend
from litterbox.core.part_number import PN
from litterbox.references import reference_reader

ASM = PN("HCR", 2, 1)
COUNTED, SUPPRESSED, EXCLUDED = sw_backend.COUNTED, sw_backend.SUPPRESSED, sw_backend.EXCLUDED


class Pretend:
    """A SolidWorks whose assemblies hold the components given ([(file name, state)]), all in the cad folder."""

    def __init__(self, cad, components, broken_count=False):
        self.cad, self.list, self.broken_count = cad, components, broken_count

    def references(self, path):
        return [(str(self.cad / name), str(self.cad / name)) for name in sorted({n for n, _s in self.list})]

    def components(self, path):
        if self.broken_count:
            raise RuntimeError("SolidWorks is busy")
        return [(str(self.cad / name), state) for name, state in self.list]


class Counting(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.cad = self.repo / "cad"
        self.cad.mkdir()
        for name in ("HCR-00002-001_A.SLDASM", "HCR-00004-001_A.SLDPRT", "HCR-00005-001_B.SLDPRT"):
            (self.cad / name).write_text("model\n", encoding="utf-8")

    def count(self, components, references=()):
        return reference_reader.read_assembly_quantities(self.repo, ASM, "A", Pretend(self.cad, components),
                                                         ["cad/HCR-00002-001_A.SLDASM"], references)

    def test_each_copy_counts_once_and_suppressed_or_excluded_ones_not_at_all(self):
        bolt, plate = "HCR-00004-001_A.SLDPRT", "HCR-00005-001_B.SLDPRT"
        found = self.count([(bolt, COUNTED)] * 4 + [(bolt, SUPPRESSED), (bolt, EXCLUDED), (plate, COUNTED),
                                                    ("screw.SLDPRT", COUNTED)])
        self.assertEqual(found, {"HCR-00004-001_A": 4, "HCR-00005-001_B": 1})        # the library screw is left out

    def test_every_part_used_gets_a_count_even_with_no_copy_counted(self):
        found = self.count([("HCR-00004-001_A.SLDPRT", EXCLUDED)], references=["HCR-00005-001_B"])
        self.assertEqual(found, {"HCR-00004-001_A": 0, "HCR-00005-001_B": 0})

    def test_a_component_whose_file_is_missing_or_not_downloaded_stops_the_count(self):
        with self.assertRaisesRegex(Exception, "could not be found"):
            self.count([("HCR-00009-001_A.SLDPRT", SUPPRESSED)])
        (self.cad / "HCR-00004-001_A.SLDPRT").write_text(
            "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 9\n", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "HCR-00004-001_A.SLDPRT could not be found"):
            self.count([("HCR-00004-001_A.SLDPRT", SUPPRESSED)])

    def test_the_check_in_reader_returns_references_and_counts(self):
        reader = reference_reader.make_reader(Pretend(self.cad, [("HCR-00004-001_A.SLDPRT", COUNTED)] * 2))
        found = reader(self.repo, ASM, "A", ["cad/HCR-00002-001_A.SLDASM"])
        self.assertEqual((found.references, found.quantities), (["HCR-00004-001_A"], {"HCR-00004-001_A": 2}))
        self.assertIsNone(reader(self.repo, ASM, "A", ["cad/HCR-00002-001_A.SLDDRW"]))

    def test_if_only_counting_fails_the_references_are_kept(self):
        log = []
        reader = reference_reader.make_reader(Pretend(self.cad, [("HCR-00004-001_A.SLDPRT", COUNTED)],
                                                      broken_count=True), log.append)
        found = reader(self.repo, ASM, "A", ["cad/HCR-00002-001_A.SLDASM"])
        self.assertEqual((found.references, found.quantities), (["HCR-00004-001_A"], None))
        self.assertIn("so its BOM needs updating", log[0])


class ComponentStates(unittest.TestCase):
    def test_suppressed_beats_excluded_and_envelopes_are_left_out(self):
        self.assertEqual(sw_backend.component_state(False, False, False), COUNTED)
        self.assertEqual(sw_backend.component_state(True, True, False), SUPPRESSED)
        self.assertEqual(sw_backend.component_state(False, True, False), EXCLUDED)
        self.assertEqual(sw_backend.component_state(False, False, True), EXCLUDED)

    def test_paths_handed_to_solidworks_are_absolute(self):
        self.assertTrue(Path(sw_backend.full_path("cad/x.SLDASM")).is_absolute())


if __name__ == "__main__":
    unittest.main()
