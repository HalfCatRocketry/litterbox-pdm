"""A temporary vault folder for the record tests (no git). No tests here."""

import re
import tempfile
import unittest
from pathlib import Path
from litterbox.records import record_store
from litterbox.core.part_number import PN


TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)

    def make(self, base, variant=1, name="Test part", org="HCR", **fields):
        return record_store.create_record(self.repo, PN(org, base, variant), name, "Alex Smith", **fields)
