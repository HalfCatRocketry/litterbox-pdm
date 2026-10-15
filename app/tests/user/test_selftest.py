"""Tests for user/selftest.py, the check the release pipeline runs on the built program (here: from source)."""

import unittest
from pathlib import Path
from unittest import mock

from litterbox.user import selftest

PACKAGE = Path(selftest.__file__).resolve().parents[1]


class SelfTest(unittest.TestCase):
    def test_it_finds_every_module_of_the_package(self):
        on_disk = {".".join(p.relative_to(PACKAGE.parent).with_suffix("").parts).removesuffix(".__init__")
                   for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts}
        on_disk.discard("litterbox.__main__")              # importing it would run the command line
        self.assertEqual(set(selftest.app_modules()), on_disk - {"litterbox"})
        self.assertGreaterEqual(len(on_disk), selftest.MIN_MODULES)

    def test_a_module_that_cannot_be_imported_is_reported(self):
        modules = selftest.app_modules() + ["litterbox.no_such_module"]
        with mock.patch.object(selftest, "app_modules", return_value=modules):
            found = selftest.problems()
        self.assertTrue(any("litterbox.no_such_module" in p for p in found), found)

    def test_a_build_that_lost_most_of_its_modules_is_reported(self):
        with mock.patch.object(selftest, "app_modules", return_value=["litterbox.version"]):
            found = selftest.problems()
        self.assertTrue(any("modules were found" in p for p in found), found)


if __name__ == "__main__":
    unittest.main()
