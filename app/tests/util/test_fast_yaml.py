"""util/fast_yaml.py: the C parser reads what the Python one does, and a damaged file is described the same way."""

import io
import unittest
from unittest import mock

import yaml

from litterbox.util import fast_yaml

SAMPLE = """\
pn: HCR-00042-001
name: "Bracket, left"
revision: B
cots: false
quantity: 3
cost: 1.50
created_at: '2026-10-01T12:00:00+00:00'
history:
- {event: created, by: Alex Example, at: '2026-10-01T12:00:00+00:00'}
- event: released
  revision: A
references: {HCR-00043-001: [A, B]}
note: "caf\\u00e9 \\u2013 ok"
empty:
"""


class FastYaml(unittest.TestCase):
    def test_reads_what_safe_load_reads(self):
        self.assertEqual(fast_yaml.safe_load(SAMPLE), yaml.safe_load(SAMPLE))

    def test_reads_an_open_file(self):
        self.assertEqual(fast_yaml.safe_load(io.StringIO(SAMPLE)), yaml.safe_load(SAMPLE))

    def test_empty_text_is_none(self):
        self.assertIsNone(fast_yaml.safe_load(""))

    def test_a_damaged_file_says_what_safe_load_says(self):
        broken = "pn: HCR-00042-001\nname: [unclosed\n"
        with self.assertRaises(yaml.YAMLError) as expected:
            yaml.safe_load(broken)
        with self.assertRaises(yaml.YAMLError) as got:
            fast_yaml.safe_load(broken)
        self.assertEqual(str(got.exception), str(expected.exception))

    def test_never_builds_python_objects(self):
        with self.assertRaises(yaml.YAMLError):
            fast_yaml.safe_load("!!python/object/apply:os.system ['echo hi']")

    def test_works_without_the_c_parser(self):
        with mock.patch.object(fast_yaml, "_FAST_LOADER", None):
            self.assertEqual(fast_yaml.safe_load(SAMPLE), yaml.safe_load(SAMPLE))


if __name__ == "__main__":
    unittest.main()
