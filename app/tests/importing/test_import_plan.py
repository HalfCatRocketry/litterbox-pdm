"""Tests for importing/import_plan.read_references: how a problem reading a file's references is reported."""

import unittest
from types import SimpleNamespace

from litterbox.cad.solidworks import sw_errors
from litterbox.importing import import_errors
from litterbox.importing import import_plan

ITEMS = [SimpleNamespace(files=[SimpleNamespace(path="/old/a.SLDPRT")])]


def backend_raising(error):
    def references(path):
        raise error
    return SimpleNamespace(references=references)


class ReadingReferences(unittest.TestCase):
    def test_a_solidworks_problem_is_passed_on_as_it_is(self):
        with self.assertRaises(sw_errors.SolidWorksError) as ctx:
            import_plan.read_references(ITEMS, backend_raising(sw_errors.SolidWorksError("SolidWorks is not open.")))
        self.assertEqual(str(ctx.exception), "SolidWorks is not open.")

    def test_an_import_problem_is_passed_on_as_it_is(self):
        with self.assertRaises(import_errors.ImportFailed) as ctx:
            import_plan.read_references(ITEMS, backend_raising(import_errors.ImportFailed("Cancelled.")))
        self.assertEqual(str(ctx.exception), "Cancelled.")

    def test_anything_else_names_the_file(self):
        with self.assertRaises(import_errors.ImportFailed) as ctx:
            import_plan.read_references(ITEMS, backend_raising(OSError("disk on fire")))
        self.assertIn("Could not read the references of /old/a.SLDPRT", str(ctx.exception))

    def test_the_references_are_returned_by_file(self):
        backend = SimpleNamespace(references=lambda path: [("x", "y")])
        refs = import_plan.read_references(ITEMS, backend)
        self.assertEqual(list(refs.values()), [("/old/a.SLDPRT", [("x", "y")])])


if __name__ == "__main__":
    unittest.main()
