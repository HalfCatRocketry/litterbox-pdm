"""docs/ARCHITECTURE.md keeps up with the code: every module appears in its map."""

import unittest

from tests.architecture.code_index import APP, modules

ARCHITECTURE = APP.parent / "docs" / "ARCHITECTURE.md"


class Docs(unittest.TestCase):
    def test_every_module_is_in_the_map(self):
        text = ARCHITECTURE.read_text(encoding="utf-8")
        missing = sorted(m.name for m in modules().values()
                         if m.path.name != "__init__.py" and f" {m.path.name}" not in text)
        self.assertEqual(missing, [], "run python tools/update_architecture_map.py")


if __name__ == "__main__":
    unittest.main()
